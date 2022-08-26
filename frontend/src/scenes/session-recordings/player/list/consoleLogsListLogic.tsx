import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'
import type { consoleLogsListLogicType } from './consoleLogsListLogicType'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { sessionRecordingLogic } from 'scenes/session-recordings/sessionRecordingLogic'
import {
    YesOrNoResponse,
    RecordingConsoleLog,
    RecordingSegment,
    RecordingTimeMixinType,
    RRWebRecordingConsoleLogPayload,
    RecordingWindowFilter,
} from '~/types'
import { eventWithTime } from 'rrweb/typings/types'
import {
    getPlayerPositionFromEpochTime,
    getPlayerTimeFromPlayerPosition,
} from 'scenes/session-recordings/player/playerUtils'
import { capitalizeFirstLetter, colonDelimitedDuration } from 'lib/utils'
import { sharedListLogic } from 'scenes/session-recordings/player/list/sharedListLogic'
import md5 from 'md5'
import { parseEntry } from 'scenes/session-recordings/player/list/consoleLogsUtils'

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
    const { level, payload: content, trace } = payload

    // Parse each string entry in content and trace
    const contentFiltered = content?.filter((entry): entry is string => !!entry) ?? []
    const traceFiltered = trace?.filter((entry): entry is string => !!entry) ?? []
    const parsedEntries = contentFiltered.map((entry) => parseEntry(entry))
    const parsedTrace = traceFiltered.map((entry) => parseEntry(entry))

    // Create a preview and full version of logs
    const previewContent = parsedEntries
        .map(({ type, size, parsed }) => {
            if (['array', 'object'].includes(type)) {
                return `${capitalizeFirstLetter(type)} (${size})`
            }
            return parsed
        })
        .flat()
    const fullContent = [
        ...parsedEntries.map(({ parsed }) => parsed),
        ...parsedTrace.map(({ parsed }) => parsed),
    ].flat()
    const traceContent = parsedTrace.map(({ traceUrl }) => traceUrl).filter((traceUrl) => !!traceUrl)

    const parsedPayload = contentFiltered
        .map((item) => (item && item.startsWith('"') && item.endsWith('"') ? item.slice(1, -1) : item))
        .join(' ')

    return {
        parsedPayload,
        previewContent,
        fullContent,
        traceContent,
        count: 1,
        hash: md5(parsedPayload),
        level,
    }
}

export const consoleLogsListLogic = kea<consoleLogsListLogicType>([
    path(['scenes', 'session-recordings', 'player', 'consoleLogsListLogic']),
    connect(() => ({
        logic: [eventUsageLogic],
        values: [sessionRecordingLogic, ['sessionPlayerData'], sharedListLogic, ['windowIdFilter']],
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
                values.data.length,
                feedback,
                'Are you finding the console log feature useful?'
            )
        },
    })),
    selectors({
        data: [
            (s) => [s.sessionPlayerData, s.windowIdFilter],
            (sessionPlayerData, windowIdFilter): RecordingConsoleLog[] => {
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
