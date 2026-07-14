import { connect, events } from 'kea'
import type { BuiltLogic, Logic, LogicBuilder } from 'kea'

import { createStreamConnection } from 'lib/api-stream'
import { liveEventsHostOrigin } from 'lib/utils/apiHost'
import { teamLogic } from 'scenes/teamLogic'

import type { LiveEvent, TeamPublicType, TeamType } from '~/types'

const DEFAULT_FLUSH_INTERVAL_MS = 300
const MINUTE_TICK_INTERVAL_MS = 60_000

export interface LiveWidgetStreamSpec {
    /** Livestream `eventType` query param, e.g. '$pageview'. Omit to stream all event types. */
    eventType?: string
    /** Livestream `columns` query param entries — the event properties the stream should include. */
    columns?: string[]
}

export interface LiveWidgetStreamOptions {
    /** Build the stream params from the current team; return null to skip connecting. */
    getStreamSpec: (team: TeamType | TeamPublicType) => LiveWidgetStreamSpec | null
    /**
     * Receives streamed events, batched on a flush interval while the tab is visible. Dispatch into
     * the consuming logic here — via its wrapper for unkeyed logics, or the passed built logic
     * (`logic.actions.x(...)`) for keyed ones.
     */
    onEvents: (liveEvents: LiveEvent[], logic: BuiltLogic) => void
    /** Fires every 60s so time-windowed state can prune old minutes even without traffic. */
    onMinuteTick?: (logic: BuiltLogic) => void
    flushIntervalMs?: number
}

/**
 * Kea logic builder wiring a livestream SSE connection into a live widget's logic: one
 * `createStreamConnection` to `${liveEventsHostOrigin()}/events` authed with the team's
 * `live_events_token`, flush-batched `onEvents` delivery, and a minute tick for window pruning.
 *
 * All resources go through `cache.disposables`, so the stream tears down when the logic unmounts
 * and pauses while the tab is hidden (reconnecting on show). The dropped span is healed by the
 * next run_widgets re-seed — live seeds are idempotent by contract (see `LiveWidgetSeedPayload`).
 *
 * The builder only adds `connect`/`events` wiring — kea-typegen cannot see builder-injected
 * symbols, so the consuming logic declares its own actions/reducers/selectors and this builder
 * dispatches into them through the callbacks.
 */
export function liveWidgetStream<L extends Logic = Logic>(options: LiveWidgetStreamOptions): LogicBuilder<L> {
    const flushIntervalMs = options.flushIntervalMs ?? DEFAULT_FLUSH_INTERVAL_MS

    return (logic) => {
        connect(() => ({ values: [teamLogic, ['currentTeam']] }))(logic)
        events(({ cache }) => ({
            afterMount: () => {
                const team = teamLogic.values.currentTeam
                const token = team?.live_events_token
                const host = liveEventsHostOrigin()
                if (!team || !token || !host) {
                    return
                }
                const spec = options.getStreamSpec(team)
                if (!spec) {
                    return
                }

                const url = new URL(`${host}/events`)
                if (spec.eventType) {
                    url.searchParams.append('eventType', spec.eventType)
                }
                if (spec.columns?.length) {
                    url.searchParams.append('columns', spec.columns.join(','))
                }

                let batch: LiveEvent[] = []

                // pauseOnPageHidden (default) aborts the stream when the tab hides and reconnects on show.
                cache.disposables.add(() => {
                    batch = []
                    const connection = createStreamConnection({
                        url,
                        token,
                        onMessage: (data) => {
                            try {
                                batch.push(JSON.parse(data) as LiveEvent)
                            } catch (error) {
                                console.error('Failed to parse live widget event:', error)
                            }
                        },
                        onError: (error) => {
                            console.error('Live widget stream error:', error)
                        },
                    })
                    return () => connection.abort()
                }, 'liveWidgetStream.connection')

                cache.disposables.add(() => {
                    const intervalId = setInterval(() => {
                        if (batch.length) {
                            options.onEvents(batch, logic)
                            batch = []
                        }
                    }, flushIntervalMs)
                    return () => clearInterval(intervalId)
                }, 'liveWidgetStream.flush')

                if (options.onMinuteTick) {
                    cache.disposables.add(() => {
                        const intervalId = setInterval(() => options.onMinuteTick?.(logic), MINUTE_TICK_INTERVAL_MS)
                        return () => clearInterval(intervalId)
                    }, 'liveWidgetStream.tick')
                }
            },
        }))(logic)
    }
}
