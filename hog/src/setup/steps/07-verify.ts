import { z } from 'zod'

import { HogError } from '@/core/errors'
import { runHogQL } from '@/posthog/query'

import type { EventsContext } from '../result'
import { runNext, type SetupRun, type Step } from '../setup-run'
import { SETUP_NEXT } from '../state'

// A client clock can run behind PostHog's, so events count by when PostHog received them, and the
// timestamp bound only keeps the query on recent partitions.
const CLOCK_SKEW = 'interval 1 day'

const CountSchema = z.number().or(z.string().regex(/^\d+$/).transform(Number))

export function eventsContext(startedAt: number, count: number | null): EventsContext {
    const since = new Date(startedAt).toISOString()
    const query = `select count() from events where created_at >= toDateTime('${since}') and timestamp >= toDateTime('${since}') - ${CLOCK_SKEW}`

    return { since, count, query }
}

export async function countEvents(run: SetupRun, events: EventsContext, timeoutMs?: number): Promise<number> {
    const response = await runHogQL(await run.api(), events.query, { timeoutMs, refresh: 'force_blocking' })
    return CountSchema.catch(0).parse(response.results[0]?.[0])
}

// Long enough for an app that just started to send its first event, short enough that the agent
// can finish its turn. Setup goes on without events, and `hog setup` keeps counting them.
const WAIT_MS = 30_000
const POLL_MS = 5_000
const MIN_QUERY_MS = 1_000

// A query that times out at the deadline, or can't reach PostHog, counts as no events, so setup
// still finishes.
async function waitForEvents(run: SetupRun, events: EventsContext): Promise<number> {
    const { runtime } = run.ctx
    const deadline = runtime.now() + WAIT_MS
    let failure: string | undefined

    for (;;) {
        const timeoutMs = Math.max(deadline - runtime.now(), MIN_QUERY_MS)
        const count = await countEvents(run, events, timeoutMs).then(
            (found) => {
                failure = undefined
                return found
            },
            (error: unknown) => {
                if (!(error instanceof HogError) || error.code !== 'network_error') {
                    throw error
                }

                failure = error.message
                return 0
            }
        )

        if (count > 0 || runtime.now() >= deadline) {
            if (failure) {
                run.context.warnings.push(`hog couldn't check for events: ${failure}`)
            }

            return count
        }

        await runtime.sleep(Math.min(POLL_MS, deadline - runtime.now()))
    }
}

export const verify: Step = {
    summary: () => 'Checked for events',

    async advance(run) {
        const events = eventsContext(run.state?.startedAt ?? 0, null)
        if (!run.input.next) {
            run.context.events = events
            return runNext(
                'setup_verify_pending',
                `Run \`${SETUP_NEXT}\` to wait up to 30 seconds for events PostHog received since ${events.since}.`
            )
        }

        const count = await waitForEvents(run, events)
        run.context.events = { ...events, count }
        await run.complete('verify')

        return undefined
    },
}
