import { actions, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import type { consoleLogsListLogicType } from './consoleLogsListLogicType'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import {
    YesOrNoResponse,
    RecordingConsoleLog,
    RecordingSegment,
    RecordingTimeMixinType,
    RRWebRecordingConsoleLogPayload,
    RecordingWindowFilter,
    SessionRecordingPlayerProps,
} from '~/types'
import { eventWithTime } from 'rrweb/typings/types'
import {
    getPlayerPositionFromEpochTime,
    getPlayerTimeFromPlayerPosition,
} from 'scenes/session-recordings/player/playerUtils'
import { colonDelimitedDuration } from 'lib/utils'
import { sharedListLogic } from 'scenes/session-recordings/player/sharedListLogic'
import { sessionRecordingPlayerLogic } from './sessionRecordingPlayerLogic'

const CONSOLE_LOG_PLUGIN_NAME = 'rrweb/console@1'

export const FEEDBACK_OPTIONS = {
    [YesOrNoResponse.Yes]: {
        value: YesOrNoResponse.Yes,
        label: '👍 Yes!',
    },
    [YesOrNoResponse.No]: {
        value: YesOrNoResponse.No,
        label: '👎 Not really',
    },
}

function parseConsoleLogPayload(
    payload: RRWebRecordingConsoleLogPayload
): Omit<RecordingConsoleLog, keyof RecordingTimeMixinType> {
    const { level, payload: logPayload, trace } = payload

    const parsedPayload = logPayload
        ?.map?.((item) => (item && item.startsWith('"') && item.endsWith('"') ? item.slice(1, -1) : item))
        .join(' ')

    // Parse the trace string
    let parsedTraceString
    let parsedTraceURL
    // trace[] contains strings that looks like:
    // * ":123:456"
    // * "https://example.com/path/to/file.js:123:456"
    // * "Login (https://example.com/path/to/file.js:123:456)"
    // Note: there may be other formats too, but we only handle these ones now
    if (trace && trace.length > 0) {
        const traceWithoutParentheses = trace[0].split('(').slice(-1)[0].replace(')', '')
        const splitTrace = traceWithoutParentheses.split(':')
        const lineNumbers = splitTrace.slice(-2).join(':')
        parsedTraceURL = splitTrace.slice(0, -2).join(':')
        if (splitTrace.length >= 4) {
            // Case with URL and line number
            try {
                const fileNameFromURL = new URL(parsedTraceURL).pathname.split('/').slice(-1)[0]
                parsedTraceString = `${fileNameFromURL}:${lineNumbers}`
            } catch (e) {
                // If we can't parse the URL, fall back to this line number
                parsedTraceString = `:${lineNumbers}`
            }
        } else {
            // Case with line number only
            parsedTraceString = `:${lineNumbers}`
        }
    }
    return {
        parsedPayload,
        parsedTraceString,
        parsedTraceURL,
        level,
    }
}

export const consoleLogsListLogic = kea<consoleLogsListLogicType>([
    path(['scenes', 'session-recordings', 'player', 'consoleLogsListLogic']),
    props({} as SessionRecordingPlayerProps),
    key((props: SessionRecordingPlayerProps) => `${props.playerKey}-${props.sessionRecordingId}`),
    connect(({ sessionRecordingId, playerKey }: SessionRecordingPlayerProps) => ({
        logic: [eventUsageLogic],
        values: [
            sessionRecordingPlayerLogic({ sessionRecordingId, playerKey }),
            ['sessionPlayerData'],
            sharedListLogic,
            ['windowIdFilter'],
        ],
    })),
    actions({
        submitFeedback: (feedback: YesOrNoResponse) => ({ feedback }),
    }),
    reducers({
        feedbackSubmitted: [
            false,
            {
                submitFeedback: () => true,
            },
        ],
    }),
    listeners(({ values }) => ({
        submitFeedback: ({ feedback }) => {
            eventUsageLogic.actions.reportRecordingConsoleFeedback(
                values.consoleLogs.length,
                feedback,
                'Are you finding the console log feature useful?'
            )
        },
    })),
    selectors({
        consoleLogs: [
            (s) => [s.sessionPlayerData, s.windowIdFilter],
            (sessionPlayerData, windowIdFilter) => {
                const logs: RecordingConsoleLog[] = []

                // Filter only snapshots from specified window
                const filteredSnapshotsByWindowId =
                    windowIdFilter === RecordingWindowFilter.All
                        ? sessionPlayerData.snapshotsByWindowId
                        : { [windowIdFilter]: sessionPlayerData.snapshotsByWindowId?.[windowIdFilter] }

                sessionPlayerData.metadata.segments.forEach((segment: RecordingSegment) => {
                    filteredSnapshotsByWindowId[segment.windowId]?.forEach((snapshot: eventWithTime) => {
                        if (
                            snapshot.type === 6 && // RRWeb plugin event type
                            snapshot.data.plugin === CONSOLE_LOG_PLUGIN_NAME &&
                            snapshot.timestamp >= segment.startTimeEpochMs &&
                            snapshot.timestamp <= segment.endTimeEpochMs
                        ) {
                            const parsed = parseConsoleLogPayload(
                                snapshot.data.payload as RRWebRecordingConsoleLogPayload
                            )

                            const playerPosition = getPlayerPositionFromEpochTime(
                                snapshot.timestamp,
                                segment.windowId,
                                sessionPlayerData.metadata.startAndEndTimesByWindowId
                            )
                            const playerTime = playerPosition
                                ? getPlayerTimeFromPlayerPosition(playerPosition, sessionPlayerData.metadata.segments)
                                : null

                            logs.push({
                                ...parsed,
                                playerTime,
                                playerPosition,
                                colonTimestamp: colonDelimitedDuration(Math.floor((playerTime ?? 0) / 1000)),
                            })
                        }
                    })
                })
                return logs
            },
        ],
    }),
])
