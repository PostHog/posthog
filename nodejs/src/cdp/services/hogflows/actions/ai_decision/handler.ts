import { DateTime } from 'luxon'

import { HogFlowAction } from '~/cdp/schema/hogflow'
import { CyclotronJobInvocationHogFlow } from '~/cdp/types'

import { HogFlowFunctionsService } from '../../hogflow-functions.service'
import { actionIdForLogging, findNextAction } from '../../hogflow-utils'
import { ActionHandler, ActionHandlerOptions, ActionHandlerResult } from '../action.interface'
import { SelectedAnswer, selectAnswer } from './answer-selection'
import { AI_DECISION_UNAVAILABLE_MESSAGE, AiDecisionClient, AiDecisionReply } from './client'
import { AiDecisionConfig, answersOf, isPlainObject, parseAiDecisionConfig } from './config'

type Action = Extract<HogFlowAction, { type: 'ai_decision' }>
type Options = ActionHandlerOptions<Action>
type Answered = Extract<AiDecisionReply, { status: 'answered' }>
type Busy = Extract<AiDecisionReply, { status: 'throttled' | 'unavailable' }>
type Prepared = { config: AiDecisionConfig; context: Record<string, unknown>; contextBytes: number }
type AiDecisionRetry = NonNullable<
    NonNullable<CyclotronJobInvocationHogFlow['state']['currentAction']>['aiDecisionRetry']
>
type TestOutput = { context: Record<string, unknown>; context_bytes: number }

const MAX_CONTEXT_BYTES = 8192
const THROTTLED_GIVE_UP_MS = 30 * 60_000
const THROTTLED_DEFAULT_WAIT_SECONDS = 5
const MAX_WAIT_SECONDS = 60
const THROTTLED_MAX_JITTER = 0.25
const MAX_UNAVAILABLE_RESCHEDULES = 5

const STATE_TOO_LARGE_MESSAGE =
    "The step's context is larger than 8 KB. Remove fields from the context or shorten them."
const MODEL_REFUSED_MESSAGE =
    "The AI model couldn't answer this request. Check the step's question, options, and context, and contact support if this keeps happening."
const THROTTLED_MESSAGE =
    "The AI service stayed busy for 30 minutes, so the step didn't get an answer. Contact support if this keeps happening."
const TEST_RUN_BUSY_MESSAGE = 'The AI service is busy. Try again in a moment.'

function failure(code: string, message: string, testOutput?: unknown): ActionHandlerResult {
    return { error: new Error(`AI decision failed (${code}): ${message}`), testOutput }
}

function percentOf(probability: number): string {
    // One decimal, so 79.5% under an 80% threshold doesn't read as 80%.
    return `${Math.round(probability * 1000) / 10}%`
}

function describeAnswer(selected: SelectedAnswer, reply: Answered): string {
    const probabilities = Object.entries(reply.probabilities)
        .map(([answer, probability]) => `${answer} ${percentOf(probability)}`)
        .join(', ')
    return `AI decision answered "${selected.answer}". Probabilities: ${probabilities}. Model: ${reply.model}.`
}

function busyCode(reply: Busy): string {
    return reply.status === 'throttled' ? 'throttled' : 'gateway_unavailable'
}

function nextWaitSeconds(retry: AiDecisionRetry, reply: Busy): number | null {
    if (reply.status === 'throttled') {
        if (Date.now() - retry.firstAttemptAt >= THROTTLED_GIVE_UP_MS) {
            return null
        }
        const wait = Math.min(reply.retryAfterSeconds ?? THROTTLED_DEFAULT_WAIT_SECONDS, MAX_WAIT_SECONDS)
        return wait * (1 + Math.random() * THROTTLED_MAX_JITTER)
    }
    if (retry.unavailableReschedules >= MAX_UNAVAILABLE_RESCHEDULES) {
        return null
    }
    return Math.min(reply.retryAfterSeconds ?? 2 ** (retry.unavailableReschedules + 1), MAX_WAIT_SECONDS)
}

export class AiDecisionHandler implements ActionHandler {
    constructor(
        private functions: HogFlowFunctionsService,
        private client?: AiDecisionClient
    ) {}

    async execute(options: Options): Promise<ActionHandlerResult> {
        const prepared = await this.prepare(options)
        if (!('config' in prepared)) {
            return prepared
        }
        const testOutput = options.testRun
            ? { context: prepared.context, context_bytes: prepared.contextBytes }
            : undefined
        if (prepared.contextBytes > MAX_CONTEXT_BYTES) {
            return failure('state_too_large', STATE_TOO_LARGE_MESSAGE, testOutput)
        }
        if (options.testRun?.mockAsyncFunctions) {
            return this.mockedAnswer(options, prepared.config, testOutput!)
        }
        return this.askTheModel(options, prepared, testOutput)
    }

    private async prepare({ invocation, action }: Options): Promise<Prepared | ActionHandlerResult> {
        let config: AiDecisionConfig
        try {
            config = parseAiDecisionConfig(action.config)
        } catch (error) {
            return failure('invalid_request', (error as Error).message)
        }
        let context: unknown
        try {
            context = await this.functions.renderAiDecisionContext(invocation, action)
        } catch (error) {
            return failure('invalid_request', `The step's context couldn't be rendered: ${String(error)}`)
        }
        if (!isPlainObject(context)) {
            return failure('invalid_request', "Set the step's context to named fields.")
        }
        return { config, context, contextBytes: Buffer.byteLength(JSON.stringify(context), 'utf8') }
    }

    private mockedAnswer(options: Options, config: AiDecisionConfig, testOutput: TestOutput): ActionHandlerResult {
        const answers = answersOf(config)
        const answer = options.testRun?.mockAnswer ?? answers[0]
        // indexOf finds an option before the trailing Unsure, so an option named "unsure" wins.
        const branchIndex = answers.indexOf(answer)
        if (branchIndex < 0) {
            return failure(
                'invalid_request',
                `The mocked answer "${answer}" isn't one of this step's answers: ${answers.join(', ')}.`,
                testOutput
            )
        }
        this.log(options, 'info', `Mocked answer: ${answer}. Turn on 'Make real HTTP requests' to ask the model.`)
        const result = { answer, mocked: true }
        return {
            nextAction: findNextAction(options.invocation.hogFlow, options.action.id, branchIndex),
            result,
            testOutput: { ...result, ...testOutput },
        }
    }

    private async askTheModel(
        options: Options,
        { config, context }: Prepared,
        testOutput: TestOutput | undefined
    ): Promise<ActionHandlerResult> {
        if (!this.client?.enabled) {
            return failure('gateway_unavailable', AI_DECISION_UNAVAILABLE_MESSAGE, testOutput)
        }
        const { invocation, action } = options
        invocation.state.currentAction!.aiDecisionRetry ??= { firstAttemptAt: Date.now(), unavailableReschedules: 0 }
        const reply = await this.client.decide({
            teamId: invocation.teamId,
            hogFlowId: invocation.hogFlow.id,
            invocationId: invocation.id,
            actionId: action.id,
            config,
            state: context,
        })
        switch (reply.status) {
            case 'answered':
                return this.followAnswer(options, config, reply, testOutput)
            case 'failed':
                return failure(reply.code, reply.message, testOutput)
            default:
                return options.testRun
                    ? failure(busyCode(reply), TEST_RUN_BUSY_MESSAGE, testOutput)
                    : this.askAgainLater(options, reply)
        }
    }

    private followAnswer(
        options: Options,
        config: AiDecisionConfig,
        reply: Answered,
        testOutput: TestOutput | undefined
    ): ActionHandlerResult {
        let selected: SelectedAnswer
        try {
            selected = selectAnswer(config, reply.probabilities)
        } catch {
            return failure('model_refused', MODEL_REFUSED_MESSAGE, testOutput)
        }
        this.log(options, 'info', describeAnswer(selected, reply))
        const result = {
            answer: selected.answer,
            probability: selected.probability,
            probabilities: reply.probabilities,
            model: reply.model,
        }
        return {
            nextAction: findNextAction(options.invocation.hogFlow, options.action.id, selected.branchIndex),
            result,
            testOutput: testOutput ? { ...result, ...testOutput } : undefined,
        }
    }

    private askAgainLater(options: Options, reply: Busy): ActionHandlerResult {
        const currentAction = options.invocation.state.currentAction!
        const retry = currentAction.aiDecisionRetry!
        const seconds = nextWaitSeconds(retry, reply)
        if (seconds === null) {
            return reply.status === 'throttled'
                ? failure('throttled', THROTTLED_MESSAGE)
                : failure('gateway_unavailable', AI_DECISION_UNAVAILABLE_MESSAGE)
        }
        if (reply.status === 'unavailable') {
            retry.unavailableReschedules++
        }
        const scheduledAt = DateTime.now().plus({ seconds })
        // Keeps a retry out of the run log's pause and resume lines, the way queue routing does.
        currentAction.routingOnlyReschedule = true
        this.log(options, 'debug', `The AI service is busy. Asking again at ${scheduledAt.toUTC().toISO()}.`)
        return { scheduledAt }
    }

    private log(options: Options, level: 'debug' | 'info', message: string): void {
        options.result.logs.push({
            level,
            timestamp: DateTime.now(),
            message: `${actionIdForLogging(options.action)} ${message}`,
        })
    }
}
