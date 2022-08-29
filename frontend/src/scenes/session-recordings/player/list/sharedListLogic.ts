import { actions, kea, reducers, path, listeners, connect } from 'kea'
import { PlayerPosition, RecordingWindowFilter, SessionRecordingTab } from '~/types'
import type { sharedListLogicType } from './sharedListLogicType'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { consoleLogsListLogic } from 'scenes/session-recordings/player/list/consoleLogsListLogic'

export type WindowOption = RecordingWindowFilter.All | PlayerPosition['windowId']

export const sharedListLogic = kea<sharedListLogicType>([
    path(['scenes', 'session-recordings', 'player', 'sharedListLogic']),
    connect({
        logic: [eventUsageLogic],
    }),
    actions(() => ({
        setTab: (tab: SessionRecordingTab) => ({ tab }),
        setWindowIdFilter: (windowId: WindowOption) => ({ windowId }),
    })),
    reducers(() => ({
        windowIdFilter: [
            RecordingWindowFilter.All as WindowOption,
            {
                setWindowIdFilter: (_, { windowId }) => windowId ?? RecordingWindowFilter.All,
            },
        ],
        tab: [
            SessionRecordingTab.EVENTS as SessionRecordingTab,
            {
                setTab: (_, { tab }) => tab,
            },
        ],
    })),
    listeners(() => ({
        setTab: ({ tab }) => {
            if (tab === SessionRecordingTab.CONSOLE) {
                eventUsageLogic
                    .findMounted()
                    ?.actions?.reportRecordingConsoleViewed(
                        consoleLogsListLogic.findMounted()?.values?.data?.length ?? 0
                    )
            }
        },
    })),
])
