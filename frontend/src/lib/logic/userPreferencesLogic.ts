import { actions, connect, kea, path, reducers } from 'kea'

import { PERSON_DEFAULT_DISPLAY_NAME_PROPERTIES } from 'lib/constants'
import { teamLogic } from 'scenes/teamLogic'

import type { userPreferencesLogicType } from './userPreferencesLogicType'

export type SqlEditorNewTabPreference = 'search' | 'editor'

// This logic is for browser stored user preferences where it's not super important that it is persisted to the server
export const userPreferencesLogic = kea<userPreferencesLogicType>([
    path(['lib', 'logic', 'userPreferencesLogic']),
    actions({
        setHidePostHogPropertiesInTable: (enabled: boolean) => ({ enabled }),
        setHideNullValues: (enabled: boolean) => ({ enabled }),
        setSqlEditorNewTabPreference: (value: SqlEditorNewTabPreference) => ({ value }),
        pinPersonProperty: (prop: string) => ({ prop }),
        unpinPersonProperty: (prop: string) => ({ prop }),
        pinGroupProperty: (prop: string) => ({ prop }),
        unpinGroupProperty: (prop: string) => ({ prop }),
        setEditorVimModeEnabled: (enabled: boolean) => ({ enabled }),
    }),
    connect(() => ({
        values: [teamLogic, ['currentTeam']],
    })),
    reducers(({ values }) => ({
        hidePostHogPropertiesInTable: [
            false,
            { persist: true },
            {
                setHidePostHogPropertiesInTable: (_, { enabled }) => enabled,
            },
        ],
        hideNullValues: [true, { persist: true }, { setHideNullValues: (_, { enabled }) => enabled }],
        sqlEditorNewTabPreference: [
            'editor' as SqlEditorNewTabPreference,
            { persist: true },
            { setSqlEditorNewTabPreference: (_, { value }) => value },
        ],
        pinnedPersonProperties: [
            [
                ...(values.currentTeam?.person_display_name_properties || PERSON_DEFAULT_DISPLAY_NAME_PROPERTIES),
                '$browser',
                '$browser_version',
            ],
            { persist: true },
            {
                pinPersonProperty: (state, { prop }) => (state.includes(prop) ? state : [...state, prop]),
                unpinPersonProperty: (state, { prop }) => state.filter((p) => p !== prop),
            },
        ],
        pinnedGroupProperties: [
            ['name'] as string[],
            { persist: true },
            {
                pinGroupProperty: (state, { prop }) => (state.includes(prop) ? state : [...state, prop]),
                unpinGroupProperty: (state, { prop }) => state.filter((p) => p !== prop),
            },
        ],
        editorVimModeEnabled: [
            false,
            { persist: true },
            {
                setEditorVimModeEnabled: (_, { enabled }) => enabled,
            },
        ],
    })),
])
