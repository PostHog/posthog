import { join } from 'node:path'

import type { Context } from '@/core/context'

import { AGENTS_FILE, blockStage } from './agents-md'
import type { DoneStep, EventsContext, SetupInput, SetupResult } from './result'
import { completed, SetupRun, type Step } from './setup-run'
import { readState, setupScope, STEP_IDS, type StepId } from './state'
import { purpose } from './steps/01-purpose'
import { login } from './steps/02-login'
import { project } from './steps/03-project'
import { agentsMd } from './steps/04-agents-md'
import { install } from './steps/05-install'
import { review } from './steps/06-review'
import { countEvents, eventsContext, verify } from './steps/07-verify'
import { ADD_SKILLS, products } from './steps/08-products'
import { mcp } from './steps/09-mcp'
import { connected } from './steps/10-connected'

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
    mcp,
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
// The count is optional, so a slow query can't hold up `hog setup`.
const SUMMARY_QUERY_TIMEOUT_MS = 5_000

async function recentEvents(run: SetupRun): Promise<EventsContext | undefined> {
    const { state, context } = run
    if (!state || !context.loggedIn || context.events?.count != null) {
        return context.events
    }

    const events = eventsContext(Math.max(state.startedAt, run.ctx.runtime.now() - SUMMARY_EVENTS_WINDOW_MS), null)
    return countEvents(run, events, SUMMARY_QUERY_TIMEOUT_MS).then(
        (count) => ({ ...events, count }),
        () => events
    )
}

const READ_PROXY = 'hog skills read instrument-reverse-proxy'

const CONNECTED =
    'PostHog is set up in this folder. The PostHog section in `AGENTS.md` lists the commands for later PostHog work.'
const NO_EVENTS = "PostHog hasn't received any events yet. Run the app and use it, then run `hog setup` to check again."
const TELL_USER = `At the end of your turn, tell the user what else PostHog can do, from \`context.products\`, and which skills named in \`context.skills\` they can add with \`${ADD_SKILLS}\`. \`hog skills search <words>\` describes the skills that match.`
const SUGGEST_PROXY = `If the app uses posthog-js and its \`api_host\` is still a PostHog host, also tell the user that a reverse proxy sends PostHog's browser requests through the app's own domain, so events, feature flags, and surveys keep loading where requests to PostHog's domains are blocked, and that \`${READ_PROXY}\` sets one up. Don't set one up unless they ask: it can need a DNS change and an organization admin.`

// Only the call that finishes setup has the lists, and a person at a terminal sees them printed.
function doneInstructions(run: SetupRun, events: EventsContext | undefined): string {
    const finishedForAgent = run.ctx.prompts === undefined && run.done.some(({ step }) => step === 'connected')

    const { mcp } = run.context
    const tellMcp =
        !finishedForAgent || !mcp || mcp.configured
            ? ''
            : mcp.foreign
              ? `Also tell the user that the \`posthog\` MCP server in \`${mcp.foreign.path}\` points at another server, and that \`${mcp.command}\` replaces it with PostHog's.`
              : `Also tell the user they can connect PostHog's MCP server with \`${mcp.command}\`.`

    return [
        CONNECTED,
        events?.count === 0 ? NO_EVENTS : '',
        finishedForAgent ? TELL_USER : '',
        finishedForAgent ? SUGGEST_PROXY : '',
        tellMcp,
    ]
        .filter(Boolean)
        .join(' ')
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
                  instructions: doneInstructions(run, events),
              }
            : {
                  kind: 'run',
                  command: 'hog auth login',
                  instructions: "PostHog is set up in this folder, but you aren't logged in. Run `hog auth login`.",
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
