import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'
import type { consoleLogsListLogicType } from './consoleLogsListLogicType'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { sessionRecordingLogic } from 'scenes/session-recordings/sessionRecordingLogic'
import {
    ConsoleFeedbackOptionValue,
    RecordingConsoleLog,
    RecordingSegment,
    RecordingTimeMixinType,
    RRWebRecordingConsoleLogPayload,
} from '~/types'
import { eventWithTime } from 'rrweb/typings/types'
import {
    getPlayerPositionFromEpochTime,
    getPlayerTimeFromPlayerPosition,
} from 'scenes/session-recordings/player/playerUtils'
import { colonDelimitedDuration } from 'lib/utils'

const CONSOLE_LOG_PLUGIN_NAME = 'rrweb/console@1'

export const FEEDBACK_OPTIONS = {
    [ConsoleFeedbackOptionValue.Yes]: {
        value: ConsoleFeedbackOptionValue.Yes,
        label: '👍 Yes!',
    },
    [ConsoleFeedbackOptionValue.No]: {
        value: ConsoleFeedbackOptionValue.No,
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
    connect(() => ({
        logic: [eventUsageLogic],
        values: [sessionRecordingLogic, ['sessionPlayerData']],
    })),
    actions({
        submitFeedback: (feedback: ConsoleFeedbackOptionValue) => ({ feedback }),
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
            (s) => [s.sessionPlayerData],
            (sessionPlayerData) => {
                const logs: RecordingConsoleLog[] = []
                sessionPlayerData.metadata.segments.forEach((segment: RecordingSegment) => {
                    sessionPlayerData.snapshotsByWindowId[segment.windowId]?.forEach((snapshot: eventWithTime) => {
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
