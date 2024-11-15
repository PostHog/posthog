import { actions, connect, kea, path, reducers, selectors } from 'kea'
import { teamLogic } from 'scenes/teamLogic'

import { AutoplayDirection, SessionRecordingSidebarStacking } from '~/types'

import type { playerSettingsLogicType } from './playerSettingsLogicType'

export enum TimestampFormat {
    Relative = 'relative',
    UTC = 'utc',
    Device = 'device',
}

export enum PlaybackMode {
    Recording = 'recording',
    Waterfall = 'waterfall',
}

// This logic contains player settings that should persist across players
// If key is not specified, it is global so it does not reset when recordings change in the main recordings page
export const playerSettingsLogic = kea<playerSettingsLogicType>([
    path(['scenes', 'session-recordings', 'player', 'playerSettingsLogic']),
    actions({
        setSkipInactivitySetting: (skipInactivitySetting: boolean) => ({ skipInactivitySetting }),
        setSpeed: (speed: number) => ({ speed }),
        setHideViewedRecordings: (hideViewedRecordings: boolean) => ({ hideViewedRecordings }),
        setAutoplayDirection: (autoplayDirection: AutoplayDirection) => ({ autoplayDirection }),
        setShowFilters: (showFilters: boolean) => ({ showFilters }),
        setQuickFilterProperties: (properties: string[]) => ({ properties }),
        setTimestampFormat: (format: TimestampFormat) => ({ format }),
        setPreferredSidebarStacking: (stacking: SessionRecordingSidebarStacking) => ({ stacking }),
        setPlaybackMode: (mode: PlaybackMode) => ({ mode }),
        setSidebarOpen: (open: boolean) => ({ open }),
        setShowMouseTail: (showMouseTail: boolean) => ({ showMouseTail }),
    }),
    connect({
        values: [teamLogic, ['currentTeam']],
    }),
    reducers(({ values }) => ({
        showFilters: [true, { persist: true }, { setShowFilters: (_, { showFilters }) => showFilters }],
        sidebarOpen: [false, { persist: true }, { setSidebarOpen: (_, { open }) => open }],
        preferredSidebarStacking: [
            SessionRecordingSidebarStacking.Horizontal as SessionRecordingSidebarStacking,
            { persist: true },
            {
                setPreferredSidebarStacking: (_, { stacking }) => stacking,
            },
        ],
        playbackMode: [
            PlaybackMode.Recording as PlaybackMode,
            { persist: true },
            {
                setPlaybackMode: (_, { mode }) => mode,
            },
        ],
        quickFilterProperties: [
            [...(values.currentTeam?.person_display_name_properties || [])] as string[],
            {
                persist: true,
            },
            {
                setQuickFilterProperties: (_, { properties }) => properties,
            },
        ],
        speed: [
            1,
            { persist: true },
            {
                setSpeed: (_, { speed }) => speed,
            },
        ],
        timestampFormat: [
            TimestampFormat.Relative as TimestampFormat,
            { persist: true },
            {
                setTimestampFormat: (_, { format }) => format,
            },
        ],
        skipInactivitySetting: [
            true,
            { persist: true },
            {
                setSkipInactivitySetting: (_, { skipInactivitySetting }) => skipInactivitySetting,
            },
        ],
        autoplayDirection: [
            'older' as AutoplayDirection,
            { persist: true },
            {
                setAutoplayDirection: (_, { autoplayDirection }) => autoplayDirection,
            },
        ],
        hideViewedRecordings: [
            false,
            { persist: true },
            {
                setHideViewedRecordings: (_, { hideViewedRecordings }) => hideViewedRecordings,
            },
        ],
        showMouseTail: [
            true,
            { persist: true },
            {
                setShowMouseTail: (_, { showMouseTail }) => showMouseTail,
            },
        ],
    })),

    selectors({
        isVerticallyStacked: [
            (s) => [s.preferredSidebarStacking],
            (preferredSidebarStacking) => preferredSidebarStacking === SessionRecordingSidebarStacking.Vertical,
        ],
    }),
])
