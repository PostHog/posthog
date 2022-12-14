import { actions, kea, reducers, path, listeners, connect, props, key } from 'kea'
import { PlayerPosition, RecordingWindowFilter, SessionRecordingPlayerTab } from '~/types'
import type { sharedListLogicType } from './sharedListLogicType'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { consoleLogsListLogic } from 'scenes/session-recordings/player/inspector/consoleLogsListLogic'
import { playerSettingsLogic } from 'scenes/session-recordings/player/playerSettingsLogic'
import { SessionRecordingPlayerLogicProps } from '../sessionRecordingPlayerLogic'

export type WindowOption = RecordingWindowFilter.All | PlayerPosition['windowId']

// Settings local to each recording
export const sharedListLogic = kea<sharedListLogicType>([
    path((key) => ['scenes', 'session-recordings', 'player', 'sharedListLogic', key]),
    props({} as SessionRecordingPlayerLogicProps),
    key((props: SessionRecordingPlayerLogicProps) => `${props.playerKey}-${props.sessionRecordingId}`),
    connect({
        logic: [eventUsageLogic],
        values: [playerSettingsLogic, ['showOnlyMatching']],
        actions: [playerSettingsLogic, ['setShowOnlyMatching']],
    }),
    actions(() => ({
        setTab: (tab: SessionRecordingPlayerTab) => ({ tab }),
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
            SessionRecordingPlayerTab.EVENTS as SessionRecordingPlayerTab,
            {
                setTab: (_, { tab }) => tab,
            },
        ],
    })),
    listeners(() => ({
        setTab: ({ tab }) => {
            if (tab === SessionRecordingPlayerTab.CONSOLE) {
                eventUsageLogic
                    .findMounted()
                    ?.actions?.reportRecordingConsoleViewed(
                        consoleLogsListLogic.findMounted()?.values?.consoleListData?.length ?? 0
                    )
            }
        },
    })),
])
