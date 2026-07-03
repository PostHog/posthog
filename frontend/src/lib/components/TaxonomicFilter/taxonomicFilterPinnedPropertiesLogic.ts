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
    /**
     * Canonical value the entry was pinned under (e.g. `action.id`,
     * `property.name`). Stored alongside the item because the reducer
     * shrinks `item` down to `{ name }` for storage; without this,
     * groups whose `getValue` reads a different field (Actions →
     * `id`) can't roundtrip into a pinned/unpinned check.
     */
    value: TaxonomicFilterValue
}

export function hasPinnedContext(item: unknown): item is Record<string, any> & { _pinnedContext: PinnedItemContext } {
    return typeof item === 'object' && item != null && '_pinnedContext' in item && (item as any)._pinnedContext != null
}

export function stripPinnedContext<T extends Record<string, any>>(item: T): Omit<T, '_pinnedContext'> {
    const { _pinnedContext: _, ...clean } = item
    return clean
}

/**
 * Fields stripped before persisting a pinned item to localStorage. The list covers
 * the obvious PII / heavy-blob fields that source-group items may carry — Person
 * `email` and `properties`, Group `group_properties`, etc. Everything else flows
 * through so source-group `getValue` and `getName` keep working without us having
 * to enumerate every identifier field they read.
 */
const PINNED_ITEM_DENYLIST = new Set<string>(['email', 'properties', 'group_properties', '_pinnedContext'])

export function pickMinimalPinnedItem(item: unknown, fallbackValue: TaxonomicFilterValue): Record<string, any> {
    if (typeof item !== 'object' || item == null || Array.isArray(item)) {
        return { name: fallbackValue }
    }
    const source = item as Record<string, any>
    const picked: Record<string, any> = {}
    for (const [field, fieldValue] of Object.entries(source)) {
        if (PINNED_ITEM_DENYLIST.has(field) || fieldValue === undefined || typeof fieldValue === 'function') {
            continue
        }
        picked[field] = fieldValue
    }
    if (picked.name == null) {
        picked.name = fallbackValue
    }
    return picked
}

const OLD_PERSIST_KEY = 'scenes.session-recordings.player.playerSettingsLogic.quickFilterProperties'

const teamId = typeof window !== 'undefined' ? window.POSTHOG_APP_CONTEXT?.current_team?.id : undefined
const MIGRATION_KEY = `taxonomicFilterPinnedProperties__migrated__${teamId ?? 'default'}`
const DEFAULTS_SEEDED_KEY = `taxonomicFilterPinnedProperties__defaultsSeeded__${teamId ?? 'default'}`

function makeDefaultPinnedFilter(
    groupType: TaxonomicFilterGroupType,
    groupName: string,
    value: string
): PinnedTaxonomicFilter {
    return { groupType, groupName, value, item: { name: value }, timestamp: Date.now() }
}

function buildDefaultPinnedFilters(): PinnedTaxonomicFilter[] {
    const appContext = window.POSTHOG_APP_CONTEXT
    const defaults: PinnedTaxonomicFilter[] = []
    if (appContext?.has_pageview) {
        defaults.push(
            makeDefaultPinnedFilter(TaxonomicFilterGroupType.EventProperties, 'Event properties', '$current_url')
        )
    }
    if (appContext?.has_person_email) {
        defaults.push(makeDefaultPinnedFilter(TaxonomicFilterGroupType.PersonProperties, 'Person properties', 'email'))
    }
    return defaults
}

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
                        item: pickMinimalPinnedItem(item, value),
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
                                value: f.value,
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

            const migrateOldQuickFilters = (): void => {
                if (localStorage.getItem(MIGRATION_KEY)) {
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
                            const migrated: PinnedTaxonomicFilter[] = oldProperties.map((prop) =>
                                makeDefaultPinnedFilter(
                                    TaxonomicFilterGroupType.PersonProperties,
                                    'Person properties',
                                    prop
                                )
                            )
                            actions.setPinnedFilters(migrated)
                            localStorage.removeItem(OLD_PERSIST_KEY)
                        }
                    }
                } catch {
                    // ignore parse errors from old data
                }
                localStorage.setItem(MIGRATION_KEY, '1')
            }

            const seedDefaultsForUntouchedUsers = (): void => {
                if (localStorage.getItem(DEFAULTS_SEEDED_KEY)) {
                    return
                }
                if (values.pinnedFilters.length > 0) {
                    localStorage.setItem(DEFAULTS_SEEDED_KEY, '1')
                    return
                }
                const defaults = buildDefaultPinnedFilters()
                if (defaults.length > 0) {
                    actions.setPinnedFilters(defaults)
                    localStorage.setItem(DEFAULTS_SEEDED_KEY, '1')
                }
            }

            migrateOldQuickFilters()
            seedDefaultsForUntouchedUsers()
        },
    })),
    permanentlyMount(),
])
