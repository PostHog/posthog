import { actions, events, kea, path, reducers, selectors } from 'kea'

import { permanentlyMount } from 'lib/utils/kea-logic-builders'

import type { taxonomicFilterPinnedPropertiesLogicType } from './taxonomicFilterPinnedPropertiesLogicType'
import { META_GROUP_TYPES, TaxonomicDefinitionTypes, TaxonomicFilterGroupType, TaxonomicFilterValue } from './types'

export interface PinnedTaxonomicFilter {
    groupType: TaxonomicFilterGroupType
    groupName: string
    value: TaxonomicFilterValue
    item: Record<string, any>
    timestamp: number
}

export interface PinnedItemContext {
    sourceGroupType: TaxonomicFilterGroupType
    sourceGroupName: string
}

export function hasPinnedContext(item: unknown): item is Record<string, any> & { _pinnedContext: PinnedItemContext } {
    return typeof item === 'object' && item != null && '_pinnedContext' in item && (item as any)._pinnedContext != null
}

export function stripPinnedContext<T extends Record<string, any>>(item: T): Omit<T, '_pinnedContext'> {
    const { _pinnedContext: _, ...clean } = item
    return clean
}

const OLD_PERSIST_KEY = 'scenes.session-recordings.player.playerSettingsLogic.quickFilterProperties'

const teamId = typeof window !== 'undefined' ? window.POSTHOG_APP_CONTEXT?.current_team?.id : undefined
const MIGRATION_KEY = `taxonomicFilterPinnedProperties__migrated__${teamId ?? 'default'}`

export const taxonomicFilterPinnedPropertiesLogic = kea<taxonomicFilterPinnedPropertiesLogicType>([
    path(['lib', 'components', 'TaxonomicFilter', 'taxonomicFilterPinnedPropertiesLogic']),
    actions({
        togglePin: (
            groupType: TaxonomicFilterGroupType,
            groupName: string,
            value: TaxonomicFilterValue,
            item: any
        ) => ({
            groupType,
            groupName,
            value,
            item,
        }),
        setPinnedFilters: (filters: PinnedTaxonomicFilter[]) => ({ filters }),
        clearPinnedFilters: true,
    }),
    reducers({
        pinnedFilters: [
            [] as PinnedTaxonomicFilter[],
            { persist: true, prefix: `${teamId}__` },
            {
                clearPinnedFilters: () => [],
                setPinnedFilters: (_, { filters }) => filters,
                togglePin: (state, { groupType, groupName, value, item }) => {
                    if (META_GROUP_TYPES.has(groupType) || value == null) {
                        return state
                    }

                    const existingIndex = state.findIndex((f) => f.groupType === groupType && f.value === value)

                    if (existingIndex !== -1) {
                        return state.filter((_, i) => i !== existingIndex)
                    }

                    const entry: PinnedTaxonomicFilter = {
                        groupType,
                        groupName,
                        value,
                        item: { name: item?.name ?? value },
                        timestamp: Date.now(),
                    }

                    return [...state, entry]
                },
            },
        ],
    }),
    selectors({
        pinnedFilterItems: [
            (s) => [s.pinnedFilters],
            (pinnedFilters: PinnedTaxonomicFilter[]): TaxonomicDefinitionTypes[] =>
                pinnedFilters.map(
                    (f) =>
                        ({
                            ...f.item,
                            _pinnedContext: {
                                sourceGroupType: f.groupType,
                                sourceGroupName: f.groupName,
                            } as PinnedItemContext,
                        }) as unknown as TaxonomicDefinitionTypes
                ),
        ],
        isPinned: [
            (s) => [s.pinnedFilters],
            (pinnedFilters: PinnedTaxonomicFilter[]) =>
                (groupType: TaxonomicFilterGroupType, value: TaxonomicFilterValue): boolean =>
                    pinnedFilters.some((f) => f.groupType === groupType && f.value === value),
        ],
    }),
    events(({ actions, values }) => ({
        afterMount: () => {
            if (typeof window === 'undefined') {
                return
            }
            const alreadyMigrated = localStorage.getItem(MIGRATION_KEY)
            if (alreadyMigrated) {
                return
            }

            if (values.pinnedFilters.length > 0) {
                localStorage.setItem(MIGRATION_KEY, '1')
                return
            }

            try {
                const raw = localStorage.getItem(OLD_PERSIST_KEY)
                if (raw) {
                    const oldProperties: string[] = JSON.parse(raw)
                    if (Array.isArray(oldProperties) && oldProperties.length > 0) {
                        const migrated: PinnedTaxonomicFilter[] = oldProperties.map((prop) => ({
                            groupType: TaxonomicFilterGroupType.PersonProperties,
                            groupName: 'Person properties',
                            value: prop,
                            item: { name: prop },
                            timestamp: Date.now(),
                        }))
                        actions.setPinnedFilters(migrated)
                        localStorage.removeItem(OLD_PERSIST_KEY)
                    }
                }
            } catch {
                // ignore parse errors from old data
            }

            localStorage.setItem(MIGRATION_KEY, '1')
        },
    })),
    permanentlyMount(),
])
