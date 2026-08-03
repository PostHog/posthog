import { MakeLogicType, actions, connect, kea, listeners, path, reducers, selectors } from 'kea'
import posthog from 'posthog-js'

import { FEATURE_FLAGS } from 'lib/constants'
import { FeatureFlagsSet, featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { uuid } from 'lib/utils/dom'
import { teamLogic } from 'scenes/teamLogic'
import { userLogic } from 'scenes/userLogic'

import {
    ProjectUIConfiguration,
    SidebarConfiguration,
    SidebarCustomGroup,
    SidebarDensity,
    SidebarItemsConfiguration,
    SidebarSectionsConfiguration,
    UserUIConfiguration,
} from '~/queries/schema/schema-general'
import { TeamPublicType, TeamType, UserType } from '~/types'

export type SidebarSectionKey = keyof SidebarSectionsConfiguration
export type SidebarItemKey = keyof SidebarItemsConfiguration

/** Version stamped onto the configuration whenever this client persists it. */
export const UI_CONFIGURATION_VERSION = 1

/** How long consecutive customization changes are batched before a single PATCH is sent. */
export const UI_CONFIGURATION_SAVE_DEBOUNCE_MS = 500

export function withSidebarSectionVisibility(
    configuration: UserUIConfiguration | null,
    section: SidebarSectionKey,
    visible: boolean
): UserUIConfiguration {
    return {
        version: UI_CONFIGURATION_VERSION,
        ...configuration,
        sidebar: {
            ...configuration?.sidebar,
            sections: {
                ...configuration?.sidebar?.sections,
                [section]: { ...configuration?.sidebar?.sections?.[section], visible },
            },
        },
    }
}

export function withSidebarItemVisibility(
    configuration: UserUIConfiguration | null,
    item: SidebarItemKey,
    visible: boolean
): UserUIConfiguration {
    return {
        version: UI_CONFIGURATION_VERSION,
        ...configuration,
        sidebar: {
            ...configuration?.sidebar,
            items: {
                ...configuration?.sidebar?.items,
                [item]: { ...configuration?.sidebar?.items?.[item], visible },
            },
        },
    }
}

export function withSidebarPatch(
    configuration: UserUIConfiguration | null,
    patch: Partial<SidebarConfiguration>
): UserUIConfiguration {
    return {
        version: UI_CONFIGURATION_VERSION,
        ...configuration,
        sidebar: { ...configuration?.sidebar, ...patch },
    }
}

export function withProjectUIConfiguration(
    configuration: UserUIConfiguration | null,
    projectId: string,
    patch: Partial<ProjectUIConfiguration>
): UserUIConfiguration {
    const projects: Record<string, ProjectUIConfiguration> = { ...configuration?.projects }
    const nextProject: ProjectUIConfiguration = { ...projects[projectId], ...patch }
    // Drop keys explicitly patched to undefined, and drop empty project entries entirely,
    // so clearing an override leaves no residue in the stored blob.
    for (const key of Object.keys(nextProject) as (keyof ProjectUIConfiguration)[]) {
        if (nextProject[key] === undefined) {
            delete nextProject[key]
        }
    }
    if (Object.keys(nextProject).length === 0) {
        delete projects[projectId]
    } else {
        projects[projectId] = nextProject
    }
    return {
        version: UI_CONFIGURATION_VERSION,
        ...configuration,
        projects,
    }
}

/**
 * Layer a user's own configuration over a base (the project default set by an admin).
 * Visibility maps merge per key so a user tweak of one item keeps the rest of the default;
 * list-shaped fields (orders, groups) are taken wholesale from whichever layer defines them,
 * because element-wise merging of orderings has no sensible meaning.
 */
export function mergeUIConfigurations(
    base: UserUIConfiguration | null,
    override: UserUIConfiguration | null
): UserUIConfiguration | null {
    if (!base) {
        return override
    }
    if (!override) {
        return base
    }
    return {
        version: UI_CONFIGURATION_VERSION,
        sidebar: {
            sections: { ...base.sidebar?.sections, ...override.sidebar?.sections },
            items: { ...base.sidebar?.items, ...override.sidebar?.items },
            flattened: override.sidebar?.flattened ?? base.sidebar?.flattened,
            density: override.sidebar?.density ?? base.sidebar?.density,
            itemOrder: override.sidebar?.itemOrder ?? base.sidebar?.itemOrder,
            toolOrder: override.sidebar?.toolOrder ?? base.sidebar?.toolOrder,
            groups: override.sidebar?.groups ?? base.sidebar?.groups,
        },
        projects: { ...base.projects, ...override.projects },
    }
}

/**
 * Apply a stored order to a list of keys: listed keys first (unknown ones ignored),
 * then the remaining keys in their default order.
 */
export function orderKeys(defaultKeys: string[], order: string[] | null | undefined): string[] {
    if (!order?.length) {
        return defaultKeys
    }
    const known = new Set(defaultKeys)
    const ordered = order.filter((key) => known.has(key))
    const orderedSet = new Set(ordered)
    return [...ordered, ...defaultKeys.filter((key) => !orderedSet.has(key))]
}

/**
 * Move `key` one step in `direction` relative to its neighbors in `renderedKeys` (the keys
 * actually displayed), returning the updated full order. Moving relative to the rendered list
 * rather than the full order matters when some keys are hidden: swapping with a hidden neighbor
 * would look like nothing happened. Returns null when the move is impossible (already at an edge).
 */
export function withKeyMovedAmong(
    fullOrder: string[],
    renderedKeys: string[],
    key: string,
    direction: 1 | -1
): string[] | null {
    const renderedIndex = renderedKeys.indexOf(key)
    if (renderedIndex === -1) {
        return null
    }
    const neighbor = renderedKeys[renderedIndex + direction]
    if (neighbor === undefined) {
        return null
    }
    const without = fullOrder.filter((existing) => existing !== key)
    const neighborIndex = without.indexOf(neighbor)
    if (neighborIndex === -1) {
        return null
    }
    const next = [...without]
    next.splice(direction === 1 ? neighborIndex + 1 : neighborIndex, 0, key)
    return next
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface uiCustomizationLogicValues {
    featureFlags: FeatureFlagsSet // featureFlagLogic
    currentProjectId: number | string // teamLogic
    currentTeam: TeamPublicType | TeamType | null // teamLogic
    user: UserType | null // userLogic
    userLoading: boolean // userLogic
    isSidebarFlattened: boolean
    isSidebarItemShown: (item: keyof SidebarItemsConfiguration) => boolean
    isSidebarSectionShown: (section: keyof SidebarSectionsConfiguration) => boolean
    pendingUiConfiguration: UserUIConfiguration | null
    projectAccentColor: string | null
    projectDefaultUiConfiguration: UserUIConfiguration | null
    resetInFlight: boolean
    sidebarDensity: SidebarDensity
    sidebarGroups: SidebarCustomGroup[]
    sidebarItemOrder: string[] | null
    sidebarToolOrder: string[] | null
    uiConfiguration: UserUIConfiguration | null
    uiCustomizationEnabled: boolean
    userUiConfiguration: UserUIConfiguration | null
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface uiCustomizationLogicActions {
    updateUser: (
        user: Partial<UserType>,
        successCallback?: (() => void) | undefined
    ) => {
        successCallback: (() => void) | undefined
        user: Partial<UserType>
    } // userLogic
    updateUserFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    } // userLogic
    updateUserSuccess: (
        user: UserType,
        payload?:
            | {
                  successCallback: (() => void) | undefined
                  user: Partial<UserType>
              }
            | undefined
    ) => {
        payload?: {
            successCallback: (() => void) | undefined
            user: Partial<UserType>
        }
        user: UserType
    } // userLogic
    applySidebarConfiguration: (
        sidebar: SidebarConfiguration | null,
        presetKey?: string
    ) => {
        presetKey: string | undefined
        sidebar: SidebarConfiguration | null
    }
    createSidebarGroup: (
        label: string,
        shortcutId?: string
    ) => {
        label: string
        shortcutId: string | undefined
    }
    deleteSidebarGroup: (groupId: string) => {
        groupId: string
    }
    persistUiConfiguration: () => {
        value: true
    }
    renameSidebarGroup: (
        groupId: string,
        label: string
    ) => {
        groupId: string
        label: string
    }
    resetUiConfiguration: () => {
        value: true
    }
    setPendingUiConfiguration: (configuration: UserUIConfiguration | null) => {
        configuration: UserUIConfiguration | null
    }
    setProjectAccentColor: (color: string | null) => {
        color: string | null
    }
    setShortcutGroup: (
        shortcutId: string,
        groupId: string | null
    ) => {
        groupId: string | null
        shortcutId: string
    }
    setSidebarDensity: (density: SidebarDensity) => {
        density: SidebarDensity
    }
    setSidebarFlattened: (flattened: boolean) => {
        flattened: boolean
    }
    setSidebarItemOrder: (order: string[]) => {
        order: string[]
    }
    setSidebarItemShown: (
        item: SidebarItemKey,
        shown: boolean
    ) => {
        item: keyof SidebarItemsConfiguration
        shown: boolean
    }
    setSidebarSectionShown: (
        section: SidebarSectionKey,
        shown: boolean
    ) => {
        section: keyof SidebarSectionsConfiguration
        shown: boolean
    }
    setSidebarToolOrder: (order: string[]) => {
        order: string[]
    }
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface uiCustomizationLogicMeta {
    __keaTypeGenInternalSelectorTypes: {
        uiCustomizationEnabled: (featureFlags: FeatureFlagsSet) => boolean
        projectDefaultUiConfiguration: (currentTeam: TeamPublicType | TeamType | null) => UserUIConfiguration | null
        userUiConfiguration: (
            user: UserType | null,
            pendingUiConfiguration: UserUIConfiguration | null,
            resetInFlight: any
        ) => UserUIConfiguration | null
        uiConfiguration: (
            userUiConfiguration: any,
            projectDefaultUiConfiguration: UserUIConfiguration | null
        ) => UserUIConfiguration | null
        isSidebarSectionShown: (
            uiConfiguration: UserUIConfiguration | null,
            uiCustomizationEnabled: boolean
        ) => (section: keyof SidebarSectionsConfiguration) => boolean
        isSidebarItemShown: (
            uiConfiguration: UserUIConfiguration | null,
            uiCustomizationEnabled: boolean
        ) => (item: keyof SidebarItemsConfiguration) => boolean
        isSidebarFlattened: (uiConfiguration: UserUIConfiguration | null, uiCustomizationEnabled: boolean) => boolean
        sidebarDensity: (uiConfiguration: UserUIConfiguration | null, uiCustomizationEnabled: boolean) => SidebarDensity
        sidebarItemOrder: (
            uiConfiguration: UserUIConfiguration | null,
            uiCustomizationEnabled: boolean
        ) => string[] | null
        sidebarToolOrder: (
            uiConfiguration: UserUIConfiguration | null,
            uiCustomizationEnabled: boolean
        ) => string[] | null
        sidebarGroups: (
            uiConfiguration: UserUIConfiguration | null,
            uiCustomizationEnabled: boolean
        ) => SidebarCustomGroup[]
        projectAccentColor: (
            uiConfiguration: UserUIConfiguration | null,
            uiCustomizationEnabled: boolean,
            currentProjectId: number | string
        ) => string | null
    }
}

export type uiCustomizationLogicType = MakeLogicType<
    uiCustomizationLogicValues,
    uiCustomizationLogicActions,
    Record<string, any>,
    uiCustomizationLogicMeta
>

/**
 * Per-user UI customization, persisted as `User.ui_configuration` (see the UserUIConfiguration schema).
 * Resolution is fail-open: a null configuration or an absent key means "shown", so nothing disappears
 * while the user is loading and newly shipped sidebar elements show for everyone until hidden explicitly.
 *
 * The effective configuration layers the user's own configuration over the project default
 * (`Team.default_ui_configuration`, set by project admins), so members who haven't customized
 * anything inherit the project's layout.
 *
 * Changes apply optimistically and are batched: consecutive changes within the debounce window
 * are persisted with a single PATCH.
 */
export const uiCustomizationLogic = kea<uiCustomizationLogicType>([
    path(['layout', 'uiCustomizationLogic']),
    connect(() => ({
        values: [
            userLogic,
            ['user', 'userLoading'],
            featureFlagLogic,
            ['featureFlags'],
            teamLogic,
            ['currentTeam', 'currentProjectId'],
        ],
        actions: [userLogic, ['updateUser', 'updateUserSuccess', 'updateUserFailure']],
    })),
    actions({
        setSidebarSectionShown: (section: SidebarSectionKey, shown: boolean) => ({ section, shown }),
        setSidebarItemShown: (item: SidebarItemKey, shown: boolean) => ({ item, shown }),
        setSidebarFlattened: (flattened: boolean) => ({ flattened }),
        setSidebarDensity: (density: SidebarDensity) => ({ density }),
        setSidebarItemOrder: (order: string[]) => ({ order }),
        setSidebarToolOrder: (order: string[]) => ({ order }),
        createSidebarGroup: (label: string, shortcutId?: string) => ({ label, shortcutId }),
        renameSidebarGroup: (groupId: string, label: string) => ({ groupId, label }),
        deleteSidebarGroup: (groupId: string) => ({ groupId }),
        setShortcutGroup: (shortcutId: string, groupId: string | null) => ({ shortcutId, groupId }),
        setProjectAccentColor: (color: string | null) => ({ color }),
        applySidebarConfiguration: (sidebar: SidebarConfiguration | null, presetKey?: string) => ({
            sidebar,
            presetKey,
        }),
        resetUiConfiguration: true,
        persistUiConfiguration: true,
        setPendingUiConfiguration: (configuration: UserUIConfiguration | null) => ({ configuration }),
    }),
    reducers({
        // Optimistic copy of the user's own configuration layer, held while changes are being
        // batched or the user PATCH is in flight, so every customization applies instantly.
        pendingUiConfiguration: [
            null as UserUIConfiguration | null,
            {
                setPendingUiConfiguration: (_, { configuration }) => configuration,
            },
        ],
        // While the reset PATCH is in flight, the stale `user.ui_configuration` must be ignored —
        // otherwise a customization made in that window would resurrect the whole pre-reset config.
        resetInFlight: [
            false,
            {
                resetUiConfiguration: () => true,
                updateUserSuccess: (state, { payload }) =>
                    payload?.user && 'ui_configuration' in payload.user ? false : state,
                updateUserFailure: () => false,
            },
        ],
    }),
    selectors({
        uiCustomizationEnabled: [
            (s) => [s.featureFlags],
            (featureFlags: FeatureFlagsSet): boolean => !!featureFlags[FEATURE_FLAGS.UI_CUSTOMIZATION],
        ],
        projectDefaultUiConfiguration: [
            (s) => [s.currentTeam],
            (currentTeam: TeamPublicType | TeamType | null): UserUIConfiguration | null => {
                const stored =
                    currentTeam && 'default_ui_configuration' in currentTeam
                        ? (currentTeam.default_ui_configuration as UserUIConfiguration | null)
                        : null
                if (!stored) {
                    return null
                }
                // Groups reference the publishing admin's own (per-user) shortcuts and accent colors
                // are personal preferences, so neither is meaningful as a project default.
                const { groups: _groups, ...sidebar } = stored.sidebar ?? {}
                return { version: stored.version, ...(stored.sidebar ? { sidebar } : {}) }
            },
        ],
        // The user's own configuration layer — what mutations build on and what gets persisted.
        userUiConfiguration: [
            (s) => [s.user, s.pendingUiConfiguration, s.resetInFlight],
            (
                user: UserType | null,
                pendingUiConfiguration: UserUIConfiguration | null,
                resetInFlight: boolean
            ): UserUIConfiguration | null =>
                pendingUiConfiguration ?? (resetInFlight ? null : (user?.ui_configuration ?? null)),
        ],
        // The effective configuration the UI renders: the user's layer over the project default.
        // Mutations must NOT build on this, or they would snapshot the whole project default into
        // the user's own configuration and freeze them off future default updates.
        uiConfiguration: [
            (s) => [s.userUiConfiguration, s.projectDefaultUiConfiguration],
            (
                userUiConfiguration: UserUIConfiguration | null,
                projectDefaultUiConfiguration: UserUIConfiguration | null
            ): UserUIConfiguration | null => mergeUIConfigurations(projectDefaultUiConfiguration, userUiConfiguration),
        ],
        // With the flag off, any stored configuration is ignored so the sidebar keeps its default layout.
        isSidebarSectionShown: [
            (s) => [s.uiConfiguration, s.uiCustomizationEnabled],
            (uiConfiguration: UserUIConfiguration | null, uiCustomizationEnabled: boolean) =>
                (section: SidebarSectionKey): boolean =>
                    !uiCustomizationEnabled || uiConfiguration?.sidebar?.sections?.[section]?.visible !== false,
        ],
        isSidebarItemShown: [
            (s) => [s.uiConfiguration, s.uiCustomizationEnabled],
            (uiConfiguration: UserUIConfiguration | null, uiCustomizationEnabled: boolean) =>
                (item: SidebarItemKey): boolean =>
                    !uiCustomizationEnabled || uiConfiguration?.sidebar?.items?.[item]?.visible !== false,
        ],
        isSidebarFlattened: [
            (s) => [s.uiConfiguration, s.uiCustomizationEnabled],
            (uiConfiguration: UserUIConfiguration | null, uiCustomizationEnabled: boolean): boolean =>
                uiCustomizationEnabled && uiConfiguration?.sidebar?.flattened === true,
        ],
        sidebarDensity: [
            (s) => [s.uiConfiguration, s.uiCustomizationEnabled],
            (uiConfiguration: UserUIConfiguration | null, uiCustomizationEnabled: boolean): SidebarDensity =>
                (uiCustomizationEnabled ? uiConfiguration?.sidebar?.density : null) ?? 'comfortable',
        ],
        sidebarItemOrder: [
            (s) => [s.uiConfiguration, s.uiCustomizationEnabled],
            (uiConfiguration: UserUIConfiguration | null, uiCustomizationEnabled: boolean): string[] | null =>
                (uiCustomizationEnabled ? uiConfiguration?.sidebar?.itemOrder : null) ?? null,
        ],
        sidebarToolOrder: [
            (s) => [s.uiConfiguration, s.uiCustomizationEnabled],
            (uiConfiguration: UserUIConfiguration | null, uiCustomizationEnabled: boolean): string[] | null =>
                (uiCustomizationEnabled ? uiConfiguration?.sidebar?.toolOrder : null) ?? null,
        ],
        sidebarGroups: [
            (s) => [s.uiConfiguration, s.uiCustomizationEnabled],
            (uiConfiguration: UserUIConfiguration | null, uiCustomizationEnabled: boolean): SidebarCustomGroup[] =>
                (uiCustomizationEnabled ? uiConfiguration?.sidebar?.groups : null) ?? [],
        ],
        projectAccentColor: [
            (s) => [s.uiConfiguration, s.uiCustomizationEnabled, s.currentProjectId],
            (
                uiConfiguration: UserUIConfiguration | null,
                uiCustomizationEnabled: boolean,
                currentProjectId: number | string | null
            ): string | null =>
                (uiCustomizationEnabled && currentProjectId != null
                    ? uiConfiguration?.projects?.[String(currentProjectId)]?.accentColor
                    : null) ?? null,
        ],
    }),
    listeners(({ actions, values, cache }) => {
        /** Apply a new user-layer configuration locally and schedule a (debounced) save. */
        const stage = (configuration: UserUIConfiguration): void => {
            actions.setPendingUiConfiguration(configuration)
            actions.persistUiConfiguration()
        }
        const captureChange = (properties: Record<string, unknown>): void => {
            posthog.capture('sidebar customization changed', properties)
        }
        return {
            setSidebarSectionShown: ({ section, shown }) => {
                stage(withSidebarSectionVisibility(values.userUiConfiguration, section, shown))
                captureChange({ element_kind: 'section', element_key: section, shown })
            },
            setSidebarItemShown: ({ item, shown }) => {
                stage(withSidebarItemVisibility(values.userUiConfiguration, item, shown))
                captureChange({ element_kind: 'item', element_key: item, shown })
            },
            setSidebarFlattened: ({ flattened }) => {
                stage(withSidebarPatch(values.userUiConfiguration, { flattened }))
                captureChange({ element_kind: 'flattened', shown: flattened })
            },
            setSidebarDensity: ({ density }) => {
                stage(withSidebarPatch(values.userUiConfiguration, { density }))
                captureChange({ element_kind: 'density', element_key: density })
            },
            setSidebarItemOrder: ({ order }) => {
                stage(withSidebarPatch(values.userUiConfiguration, { itemOrder: order }))
                captureChange({ element_kind: 'item_order' })
            },
            setSidebarToolOrder: ({ order }) => {
                stage(withSidebarPatch(values.userUiConfiguration, { toolOrder: order }))
                captureChange({ element_kind: 'tool_order' })
            },
            createSidebarGroup: ({ label, shortcutId }) => {
                const group: SidebarCustomGroup = { id: uuid(), label, items: shortcutId ? [shortcutId] : [] }
                const groups = shortcutId
                    ? values.sidebarGroups.map((existing) => ({
                          ...existing,
                          items: existing.items?.filter((id) => id !== shortcutId),
                      }))
                    : values.sidebarGroups
                stage(withSidebarPatch(values.userUiConfiguration, { groups: [...groups, group] }))
                captureChange({ element_kind: 'group', element_key: 'created' })
            },
            renameSidebarGroup: ({ groupId, label }) => {
                const groups = values.sidebarGroups.map((group) => (group.id === groupId ? { ...group, label } : group))
                stage(withSidebarPatch(values.userUiConfiguration, { groups }))
                captureChange({ element_kind: 'group', element_key: 'renamed' })
            },
            deleteSidebarGroup: ({ groupId }) => {
                const groups = values.sidebarGroups.filter((group) => group.id !== groupId)
                stage(withSidebarPatch(values.userUiConfiguration, { groups }))
                captureChange({ element_kind: 'group', element_key: 'deleted' })
            },
            setShortcutGroup: ({ shortcutId, groupId }) => {
                const groups = values.sidebarGroups.map((group) => {
                    const withoutShortcut = group.items?.filter((id) => id !== shortcutId)
                    return group.id === groupId
                        ? { ...group, items: [...(withoutShortcut ?? []), shortcutId] }
                        : { ...group, items: withoutShortcut }
                })
                stage(withSidebarPatch(values.userUiConfiguration, { groups }))
                captureChange({ element_kind: 'group', element_key: groupId ? 'item_added' : 'item_removed' })
            },
            setProjectAccentColor: ({ color }) => {
                if (values.currentProjectId == null) {
                    return
                }
                stage(
                    withProjectUIConfiguration(values.userUiConfiguration, String(values.currentProjectId), {
                        accentColor: color ?? undefined,
                    })
                )
                captureChange({ element_kind: 'accent_color', shown: !!color })
            },
            applySidebarConfiguration: ({ sidebar, presetKey }) => {
                const configuration: UserUIConfiguration = {
                    version: UI_CONFIGURATION_VERSION,
                    // Per-project overrides (accent colors) survive layout presets.
                    projects: values.userUiConfiguration?.projects,
                }
                if (sidebar) {
                    configuration.sidebar = sidebar
                }
                stage(configuration)
                captureChange({ element_kind: 'preset', element_key: presetKey ?? 'custom' })
            },
            resetUiConfiguration: () => {
                // Applies optimistically via the resetInFlight reducer; changes staged while the
                // PATCH is in flight build on the post-reset (null) user layer and, because the
                // in-flight lock is taken here too, only get sent once the reset has settled.
                actions.setPendingUiConfiguration(null)
                cache.uiConfigurationSaveInFlight = true
                actions.updateUser({ ui_configuration: null })
                captureChange({ element_kind: 'reset' })
            },
            // Batches rapid consecutive changes into a single PATCH (the breakpoint restarts the
            // debounce window every time another change is staged). Saves are strictly serialized:
            // while one PATCH is in flight nothing else is sent, and the settle handlers below
            // re-schedule when newer changes accumulated meanwhile. The tradeoff of batching is
            // that changes made within the debounce window of a full page unload are lost.
            persistUiConfiguration: async (_, breakpoint) => {
                await breakpoint(UI_CONFIGURATION_SAVE_DEBOUNCE_MS)
                if (cache.uiConfigurationSaveInFlight) {
                    return
                }
                const configuration = values.pendingUiConfiguration
                if (!configuration) {
                    return
                }
                cache.uiConfigurationSaveInFlight = true
                actions.updateUser({ ui_configuration: configuration })
            },
            // The success payload carries the exact partial that was sent, so the settled request
            // is attributed precisely: only clear the optimistic copy when it covered the latest
            // local change, and follow up with another save when newer changes are still pending.
            updateUserSuccess: ({ payload }) => {
                if (!payload?.user || !('ui_configuration' in payload.user)) {
                    return
                }
                cache.uiConfigurationSaveInFlight = false
                if (payload.user.ui_configuration === values.pendingUiConfiguration) {
                    actions.setPendingUiConfiguration(null)
                } else if (values.pendingUiConfiguration) {
                    actions.persistUiConfiguration()
                }
            },
            // Failures carry no request payload; assume our save failed when one was in flight and
            // fall back to the server state rather than retrying a potentially-invalid config.
            updateUserFailure: () => {
                if (cache.uiConfigurationSaveInFlight) {
                    cache.uiConfigurationSaveInFlight = false
                    actions.setPendingUiConfiguration(null)
                }
            },
        }
    }),
])
