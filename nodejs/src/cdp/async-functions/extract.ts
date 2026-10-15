import { DateTime } from 'luxon'

import { HogFlow, HogFlowAction } from '~/cdp/schema/hogflow'
import { defaultConfig } from '~/common/config/config'

import { registerAsyncFunction } from '../async-function-registry'
import { PosthogJwtAudience } from '../utils/jwt-utils'
import { ScopedServiceJwt } from '../utils/scoped-service-jwt'
import { callInternalApi } from './internal-api-call'
import { assertWorkflowContextFits } from './workflow-ai-context'

let extractJwt: ScopedServiceJwt | undefined
const getExtractJwt = (): ScopedServiceJwt =>
    (extractJwt ??= new ScopedServiceJwt(
        PosthogJwtAudience.WORKFLOW_EXTRACT,
        defaultConfig.WORKFLOW_EXTRACT_JWT_SECRET
    ))

// Django gives the model 8 seconds (EXTRACTION_TIMEOUT_SECONDS in ai_extraction.py) and returns a 503 on a
// timeout, which this worker retries. The worker does not retry its own timeout, for the reason given in
// classify.ts: the model may still be answering, and a retry would pay for the same extraction again.
const EXTRACT_TIMEOUT_MS = 10_000

// Match the limits of the extraction endpoint (the request serializer in workflow_extractions.py),
// so a mocked test run fails on the same inputs as a live run.
const MAX_FIELDS = 20
const FIELD_NAME = /^[A-Za-z_][A-Za-z0-9_]{0,63}$/
const MAX_INSTRUCTION_LENGTH = 500
const RUN_ID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i

type FieldType = 'string' | 'number' | 'boolean'
const FIELD_TYPE_LABELS: Record<FieldType, string> = { string: 'text', number: 'number', boolean: 'true or false' }
const FIELD_TYPES: ReadonlySet<string> = new Set(Object.keys(FIELD_TYPE_LABELS))

type ExtractPayload = { context: unknown; taskRunId: string | null; fields: Record<string, string> }

// The step test panel mocks async functions by default, so `mock` runs these checks too.
const parseExtractPayload = (args: any[]): ExtractPayload => {
    const [payload] = args as [Record<string, unknown> | undefined]
    const fields = payload?.fields
    if (!fields || typeof fields !== 'object' || Object.keys(fields).length === 0) {
        throw new Error('Enter at least one field')
    }
    if (Object.keys(fields).length > MAX_FIELDS) {
        throw new Error(`Enter at most ${MAX_FIELDS} fields`)
    }
    for (const [name, instruction] of Object.entries(fields)) {
        if (!FIELD_NAME.test(name)) {
            throw new Error(
                `Use only letters, digits and underscores in the field name "${name}", start it with a letter or underscore, and keep it to 64 characters`
            )
        }
        if (typeof instruction !== 'string' || !instruction.trim()) {
            throw new Error(`Say what to put in ${name}`)
        }
        if ([...instruction.trim()].length > MAX_INSTRUCTION_LENGTH) {
            throw new Error(`Keep field instructions to ${MAX_INSTRUCTION_LENGTH} characters or fewer`)
        }
    }
    const taskRunId = typeof payload.task_run_id === 'string' && payload.task_run_id ? payload.task_run_id : null
    if (taskRunId !== null && !RUN_ID.test(taskRunId)) {
        throw new Error(
            `Enter the run ID of an AI task step in AI task run, such as {variables.task.run_id}, not "${taskRunId}"`
        )
    }
    const context = payload.context ?? null
    if (context === null && taskRunId === null) {
        throw new Error('Enter the text to read, or an AI task run to read')
    }
    assertWorkflowContextFits(context, 'the text to read')
    return { context, taskRunId, fields: fields as Record<string, string> }
}

const fieldTypesFromOutputVariables = (
    action: HogFlowAction | undefined,
    variables: HogFlow['variables']
): Map<string, FieldType> => {
    const outputVariable = action?.output_variable
    const mappings = Array.isArray(outputVariable) ? outputVariable : outputVariable ? [outputVariable] : []
    const variableTypes = new Map((variables ?? []).map((variable) => [variable.key, variable.type]))
    const types = new Map<string, FieldType>()
    for (const mapping of mappings) {
        const type = variableTypes.get(mapping.key)
        if (!mapping.result_path || !type || !FIELD_TYPES.has(type)) {
            continue
        }
        const earlierType = types.get(mapping.result_path)
        if (earlierType && earlierType !== type) {
            throw new Error(
                `Map ${mapping.result_path} into variables of one type. It goes into both a ${FIELD_TYPE_LABELS[earlierType]} and a ${FIELD_TYPE_LABELS[type as FieldType]} variable.`
            )
        }
        types.set(mapping.result_path, type as FieldType)
    }
    return types
}

registerAsyncFunction('postHogExtract', {
    execute: async (args, context, result) => {
        const payload = parseExtractPayload(args)

        const hogFlow = (context.invocation as { hogFlow?: HogFlow }).hogFlow
        if (!hogFlow?.id) {
            throw new Error('Extract with AI only runs inside a workflow')
        }

        const jwt = getExtractJwt()
        if (!jwt.enabled) {
            throw new Error(
                'Extract with AI is not configured. Set WORKFLOW_EXTRACT_JWT_SECRET on the worker and Django to matching keys.'
            )
        }

        const action = hogFlow.actions?.find((candidate) => candidate.id === context.invocation.state.actionId)
        const types = fieldTypesFromOutputVariables(action, hogFlow.variables)
        result.logs.push({
            level: 'info',
            timestamp: DateTime.now(),
            message: payload.taskRunId
                ? `Extract with AI reads the full report of AI task run ${payload.taskRunId}.`
                : 'Extract with AI reads Text to read.',
        })
        await callInternalApi(context, result, {
            jwt,
            path: `/api/projects/${context.invocation.teamId}/workflow_extractions/`,
            method: 'POST',
            entityClaims: { hog_flow_id: hogFlow.id },
            body: JSON.stringify({
                context: payload.context,
                task_run_id: payload.taskRunId,
                output_fields: Object.entries(payload.fields).map(([name, instruction]) => ({
                    name,
                    type: types.get(name) ?? 'string',
                    instruction: instruction.trim(),
                })),
            }),
            timeoutMs: EXTRACT_TIMEOUT_MS,
            retryOnTimeout: false,
        })
    },
    mock: (args, logs) => {
        const payload = parseExtractPayload(args)
        logs.push({
            level: 'info',
            timestamp: DateTime.now(),
            message: 'Extract with AI was mocked. Every field came back empty without asking the model.',
        })
        return {
            status: 200,
            body: { values: Object.fromEntries(Object.keys(payload.fields).map((name) => [name, null])) },
        }
    },
})
