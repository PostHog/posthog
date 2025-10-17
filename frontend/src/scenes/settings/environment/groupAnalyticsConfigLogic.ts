import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'

import { groupsModel } from '~/models/groupsModel'

import type { groupAnalyticsConfigLogicType } from './groupAnalyticsConfigLogicType'

export const groupAnalyticsConfigLogic = kea<groupAnalyticsConfigLogicType>([
    path(['scenes', 'project', 'Settings', 'groupAnalyticsConfigLogic']),
    connect(() => ({
        values: [groupsModel, ['groupTypes', 'groupTypesLoading']],
        actions: [groupsModel, ['updateGroupTypesMetadata', 'deleteGroupType', 'loadAllGroupTypes']],
    })),
    actions({
        setSingular: (groupTypeIndex: number, value: string) => ({ groupTypeIndex, value }),
        setPlural: (groupTypeIndex: number, value: string) => ({ groupTypeIndex, value }),
        reset: true,
        save: true,
    }),
    reducers({
        singularChanges: [
            {} as Record<number, string | undefined>,
            {
                setSingular: (state, { groupTypeIndex, value }) => ({ ...state, [groupTypeIndex]: value }),
                reset: () => ({}),
                updateGroupTypesMetadataSuccess: () => ({}),
            },
        ],
        pluralChanges: [
            {} as Record<number, string | undefined>,
            {
                setPlural: (state, { groupTypeIndex, value }) => ({ ...state, [groupTypeIndex]: value }),
                reset: () => ({}),
                updateGroupTypesMetadataSuccess: () => ({}),
            },
        ],
    }),
    selectors({
        hasChanges: [
            (s) => [s.singularChanges, s.pluralChanges],
            (singularChanges, pluralChanges) =>
                Object.keys(singularChanges).length > 0 || Object.keys(pluralChanges).length > 0,
        ],
    }),
    listeners(({ values, actions }) => ({
        save: () => {
            const { groupTypes, singularChanges, pluralChanges } = values
            const payload = Array.from(groupTypes.values()).map((groupType) => {
                const result = { ...groupType }
                if (singularChanges[groupType.group_type_index]) {
                    result.name_singular = singularChanges[groupType.group_type_index]
                }
                if (pluralChanges[groupType.group_type_index]) {
                    result.name_plural = pluralChanges[groupType.group_type_index]
                }
                return result
            })

            actions.updateGroupTypesMetadata(payload)
        },
    })),
])
