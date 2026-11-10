import { z } from 'zod'

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

export async function countEvents(run: SetupRun, events: EventsContext): Promise<number> {
    const response = await runHogQL(await run.api(), events.query)
    return CountSchema.catch(0).parse(response.results[0]?.[0])
}

export const verify: Step = {
    summary: () => 'PostHog received events',

    async advance(run) {
        const events = eventsContext(run.state?.startedAt ?? 0, null)
        const ask = `Run the app and trigger an event, or ask the user to. Then run \`${SETUP_NEXT}\` to check for events received since ${events.since}.`

        if (!run.input.next) {
            run.context.events = events
            return runNext('setup_no_events_yet', ask)
        }

        const count = await countEvents(run, events)
        run.context.events = { ...events, count }
        if (count > 0) {
            await run.complete('verify')
            return undefined
        }

        return runNext('setup_no_events_yet', `PostHog hasn't received any events since setup started. ${ask}`)
    },
}
