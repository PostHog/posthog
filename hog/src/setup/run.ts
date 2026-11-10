import { join } from 'node:path'

import type { Context } from '@/core/context'

import { AGENTS_FILE, blockStage } from './agents-md'
import type { DoneStep, EventsContext, SetupInput, SetupResult } from './result'
import { completed, SetupRun, type Step } from './setup-run'
import { readState, setupScope, STEP_IDS, type StepId } from './state'
import { purpose } from './steps/1-purpose'
import { login } from './steps/2-login'
import { project } from './steps/3-project'
import { agentsMd } from './steps/4-agents-md'
import { install } from './steps/5-install'
import { review } from './steps/6-review'
import { countEvents, eventsContext, verify } from './steps/7-verify'
import { products } from './steps/8-products'
import { connected } from './steps/9-connected'

// README.md in this folder draws how the steps run, stop and resume.
const STEPS: Record<StepId, Step> = {
    purpose,
    login,
    project,
    'agents-md': agentsMd,
    install,
    review,
    verify,
    products,
    connected,
}

const SUMMARY_EVENTS_WINDOW_MS = 24 * 60 * 60 * 1000

function isDone(run: SetupRun, id: StepId): Promise<boolean> {
    return STEPS[id].isDone?.(run) ?? Promise.resolve(completed(run, id))
}

async function doneSteps(run: SetupRun): Promise<DoneStep[]> {
    const steps = await Promise.all(
        STEP_IDS.map(async (id) => ((await isDone(run, id)) ? { step: id, summary: await STEPS[id].summary(run) } : []))
    )
    return steps.flat()
}

// The count covers the last day at most, so a folder connected long ago doesn't scan every event
// since. A count that fails, such as without query:read, leaves the summary without it.
async function recentEvents(run: SetupRun): Promise<EventsContext | undefined> {
    const { state, context } = run
    if (!state || !context.loggedIn || context.events?.count != null) {
        return context.events
    }

    const events = eventsContext(Math.max(state.startedAt, run.ctx.runtime.now() - SUMMARY_EVENTS_WINDOW_MS), null)
    return countEvents(run, events).then(
        (count) => ({ ...events, count }),
        () => events
    )
}

// Once connected, `hog setup` reports the folder instead of a step.
async function connectedResult(run: SetupRun): Promise<SetupResult> {
    await run.fillLoginContext()

    const [events, done] = await Promise.all([recentEvents(run), run.done.length > 0 ? run.done : doneSteps(run)])
    const { context } = run
    context.events = events
    context.agentsMd ??= [{ path: join(run.scope.folder, AGENTS_FILE), status: 'unchanged' }]

    return {
        step: 'connected',
        status: 'connected',
        code: null,
        done,
        context,
        next: context.loggedIn
            ? {
                  kind: 'done',
                  instructions:
                      'PostHog is set up in this folder. The note in AGENTS.md lists the commands for later PostHog work.',
              }
            : {
                  kind: 'run',
                  command: 'hog auth login',
                  instructions: 'PostHog is set up in this folder. Run `hog auth login` to use hog here.',
              },
    }
}

// A clone without the state file counts as connected when its AGENTS.md has the final note and
// posthog.json names a project.
async function cloneIsConnected(run: SetupRun): Promise<boolean> {
    const [loaded, stage] = await Promise.all([run.ctx.config(), blockStage(run.ctx.runtime, run.scope.folder)])
    const config = loaded?.config

    return config?.host !== undefined && config.projectId !== undefined && stage === 'final'
}

// `hog setup` (next false) only describes. `hog setup next` does the current step and every step
// after it that needs nobody, and stops at the first one that needs the person or the agent.
export async function runSetup(ctx: Context, input: SetupInput): Promise<SetupResult> {
    const scope = await setupScope(ctx)
    const run = new SetupRun(ctx, input, scope, await readState(ctx, scope))

    if (completed(run, 'connected') || (run.state === undefined && (await cloneIsConnected(run)))) {
        return connectedResult(run)
    }

    for (const id of STEP_IDS) {
        if (!(await isDone(run, id))) {
            run.firstStep ??= id
            const stop = await STEPS[id].advance(run)
            if (stop) {
                await run.fillLoginContext()
                return { step: id, status: 'in_progress', ...stop, done: run.done, context: run.context }
            }
        }

        run.done.push({ step: id, summary: await STEPS[id].summary(run) })
    }

    return connectedResult(run)
}
