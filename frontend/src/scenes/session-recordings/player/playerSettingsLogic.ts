import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { actionToUrl, router, urlToAction } from 'kea-router'
import { subscriptions } from 'kea-subscriptions'
import posthog from 'posthog-js'
import { teamLogic } from 'scenes/teamLogic'

import { AutoplayDirection, SessionRecordingSidebarStacking } from '~/types'

import type { playerSettingsLogicType } from './playerSettingsLogicType'

export enum TimestampFormat {
    Relative = 'relative',
    UTC = 'utc',
    Device = 'device',
}

export type HideViewedRecordingsOptions = 'current-user' | 'any-user' | false

// This logic contains player settings that should persist across players
// If key is not specified, it is global so it does not reset when recordings change in the main recordings page
export const playerSettingsLogic = kea<playerSettingsLogicType>([
    path(['scenes', 'session-recordings', 'player', 'playerSettingsLogic']),
    actions({
        setSkipInactivitySetting: (skipInactivitySetting: boolean) => ({ skipInactivitySetting }),
        setSpeed: (speed: number) => ({ speed }),
        setHideViewedRecordings: (hideViewedRecordings: HideViewedRecordingsOptions) => ({
            hideViewedRecordings,
        }),
        setAutoplayDirection: (autoplayDirection: AutoplayDirection) => ({ autoplayDirection }),
        setShowFilters: (showFilters: boolean) => ({ showFilters }),
        setQuickFilterProperties: (properties: string[]) => ({ properties }),
        setTimestampFormat: (format: TimestampFormat) => ({ format }),
        setPlaylistTimestampFormat: (format: TimestampFormat) => ({ format }),
        setPreferredSidebarStacking: (stacking: SessionRecordingSidebarStacking) => ({ stacking }),
        setSidebarOpen: (open: boolean) => ({ open }),
        setPlaylistOpen: (open: boolean) => ({ open }),
        setURLOverrideSidebarOpen: (open: boolean) => ({ open }),
        setIsZenMode: (isZenMode: boolean) => ({ isZenMode }),
    }),
    connect(() => ({
        values: [teamLogic, ['currentTeam']],
    })),
    reducers(({ values }) => ({
        showFilters: [true, { persist: true }, { setShowFilters: (_, { showFilters }) => showFilters }],
        userPreferenceSidebarOpen: [false, { persist: true }, { setSidebarOpen: (_, { open }) => open }],
        urlOverrideSidebarOpen: [
            null as boolean | null,
            { persist: false },
            { setURLOverrideSidebarOpen: (_, { open }) => open },
        ],
        playlistOpen: [true, { setPlaylistOpen: (_, { open }) => open }],
        preferredSidebarStacking: [
            SessionRecordingSidebarStacking.Horizontal as SessionRecordingSidebarStacking,
            { persist: true },
            {
                setPreferredSidebarStacking: (_, { stacking }) => stacking,
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
        playlistTimestampFormat: [
            TimestampFormat.Relative as TimestampFormat,
            { persist: true },
            {
                setPlaylistTimestampFormat: (_, { format }) => format,
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
            false as HideViewedRecordingsOptions,
            { persist: true },
            {
                setHideViewedRecordings: (_, { hideViewedRecordings }) => hideViewedRecordings,
            },
        ],
        isZenMode: [
            false,
            { persist: true },
            {
                setIsZenMode: (_, { isZenMode }) => isZenMode,
            },
        ],
    })),

    selectors({
        sidebarOpen: [
            (s) => [s.userPreferenceSidebarOpen, s.urlOverrideSidebarOpen],
            (userPreferenceSidebarOpen, urlOverrideSidebarOpen): boolean => {
                if (urlOverrideSidebarOpen !== null) {
                    return urlOverrideSidebarOpen
                }
                return userPreferenceSidebarOpen
            },
        ],
        isVerticallyStacked: [
            (s) => [s.preferredSidebarStacking],
            (preferredSidebarStacking) => preferredSidebarStacking === SessionRecordingSidebarStacking.Vertical,
        ],
        hideRecordingsMenuLabelFor: [
            () => [],
            () => {
                return (option: HideViewedRecordingsOptions) => {
                    switch (option) {
                        case 'current-user':
                            return 'Hide my viewed recordings'
                        case 'any-user':
                            return 'Hide all viewed recordings'
                        default:
                            return 'Show all recordings'
                    }
                }
            },
        ],
    }),

    listeners({
        setSpeed: ({ speed }) => {
            posthog.capture('recording player speed changed', { new_speed: speed })
        },
        setSkipInactivitySetting: ({ skipInactivitySetting }) => {
            posthog.capture('recording player skip inactivity toggled', { skip_inactivity: skipInactivitySetting })
        },
    }),

    subscriptions(({ actions }) => ({
        hideViewedRecordings: ({ hideViewedRecordings }) => {
            // hideViewRecordings used to be flat boolean
            // if someone has it set to true, we should set it to 'current-user'
            // to upgrade them to the new behavior
            // this can be deleted after a few weeks
            if (hideViewedRecordings === true) {
                actions.setHideViewedRecordings('current-user')
            }
        },
    })),

    urlToAction(({ actions, values }) => ({
        // intentionally locked to replay/* to prevent other pages from setting the tab
        // this is a debug affordance
        ['**/replay/*']: (_, searchParams) => {
            // this is a debug affordance, so we only listen to whether it should be open, not also closed
            const inspectorSideBarOpen = searchParams.inspectorSideBar === true
            if (inspectorSideBarOpen && inspectorSideBarOpen !== values.sidebarOpen) {
                actions.setSidebarOpen(inspectorSideBarOpen)
            }
        },
        ['**/shared/*']: (_, searchParams) => {
            // when sharing a recording, you can specify whether the inspector should be open.
            // we should obey that regardless of the preference stored here.
            // the sharing URLs historically added showInspector with no value.
            // so we need to check for the presence of the key.
            // if the key is present but "null", that is equivalent to true
            const inspectorSideBarOpen = 'showInspector' in searchParams && (searchParams.showInspector ?? true)
            if (inspectorSideBarOpen && inspectorSideBarOpen !== values.sidebarOpen) {
                actions.setURLOverrideSidebarOpen(inspectorSideBarOpen)
            }
        },
    })),

    actionToUrl(() => ({
        setSidebarOpen: ({ open }) => {
            const { currentLocation } = router.values
            return [
                currentLocation.pathname,
                {
                    ...currentLocation.searchParams,
                    inspectorSideBar: open,
                },
                currentLocation.hashParams,
            ]
        },
    })),
])
