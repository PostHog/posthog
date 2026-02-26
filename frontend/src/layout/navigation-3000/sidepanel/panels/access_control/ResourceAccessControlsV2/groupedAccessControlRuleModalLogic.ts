import { actions, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'

import { APIScopeObject, AccessControlLevel, EffectiveAccessControlEntry } from '~/types'

import { accessControlsLogic } from './accessControlsLogic'
import type { groupedAccessControlRuleModalLogicType } from './groupedAccessControlRuleModalLogicType'
import { getEntryId, getInheritedReasonTooltip, getLevelOptionsForResource, getMinLevelDisabledReason } from './helpers'
import { FormAccessLevel, GroupedAccessControlRuleModalLogicProps } from './types'

export const groupedAccessControlRuleModalLogic = kea<groupedAccessControlRuleModalLogicType>([
    path((key) => ['scenes', 'access_control', 'groupedAccessControlRuleModalLogic', key]),
    key((props) => getEntryId(props.entry)),
    props({} as GroupedAccessControlRuleModalLogicProps),

    connect((props: GroupedAccessControlRuleModalLogicProps) => ({
        actions: [accessControlsLogic({ projectId: props.projectId }), ['saveGroupedRules', 'closeRuleModal']],
        values: [
            accessControlsLogic({ projectId: props.projectId }),
            ['loading', 'canEdit', 'availableProjectLevels', 'availableResourceLevels'],
        ],
    })),

    actions({
        setProjectLevel: (level: AccessControlLevel | null) => ({ level }),
        setResourceLevel: (resource: APIScopeObject, level: AccessControlLevel | null) => ({ resource, level }),
        setResourceLevels: (levels: Record<APIScopeObject, FormAccessLevel>) => ({ levels }),
        clearResourceOverrides: true,
        close: true,
        save: true,
    }),

    reducers(({ props }) => ({
        formProjectLevel: [
            props.entry.project.effective_access_level as FormAccessLevel,
            {
                setProjectLevel: (_, { level }) => level,
            },
        ],
        formResourceLevels: [
            Object.fromEntries(
                Object.entries(props.entry.resources).map(([key, data]) => [key, data.effective_access_level])
            ) as Record<APIScopeObject, FormAccessLevel>,
            {
                setResourceLevel: (state, { resource, level }) => ({
                    ...state,
                    [resource]: level,
                }),
                setResourceLevels: (_, { levels }) => levels,
            },
        ],
    })),

    selectors({
        entry: [(_, p) => [p.entry], (entry) => entry],
        scopeType: [(_, p) => [p.scopeType], (scopeType) => scopeType],
        entryId: [(_, p) => [p.entry], (entry) => getEntryId(entry)],

        modalTitle: [
            (s) => [s.scopeType],
            (scopeType) => {
                switch (scopeType) {
                    case 'default':
                        return 'Update default access'
                    case 'role':
                        return 'Update role access'
                    case 'member':
                        return 'Update member access'
                }
            },
        ],
        isOrgAdmin: [(s) => [s.entry], (entry) => entry.project.inherited_access_level_reason === 'organization_admin'],
        featuresDisabledReason: [
            (s) => [s.loading, s.canEdit, s.isOrgAdmin],
            (loading, canEdit, isOrgAdmin) => {
                if (loading) {
                    return 'Loading...'
                }
                if (!canEdit) {
                    return 'Cannot edit'
                }
                if (isOrgAdmin) {
                    return 'User is an organization admin and has access to all features'
                }
                return undefined
            },
        ],

        // Project access level
        isProjectLevelShowingInherited: [
            (s) => [s.formProjectLevel, s.entry],
            (formProjectLevel, entry) =>
                formProjectLevel === entry.project.inherited_access_level &&
                entry.project.inherited_access_level !== null,
        ],
        projectInheritedReasonTooltip: [
            (s) => [s.isProjectLevelShowingInherited, s.entry],
            (isProjectLevelShowingInherited, entry) =>
                isProjectLevelShowingInherited
                    ? getInheritedReasonTooltip(entry.project.inherited_access_level_reason)
                    : undefined,
        ],
        projectLevelOptions: [
            (s) => [s.availableProjectLevels, s.entry],
            (availableProjectLevels, entry) => {
                const { inherited_access_level, inherited_access_level_reason, minimum } = entry.project
                return getLevelOptionsForResource(availableProjectLevels, {
                    minimum: inherited_access_level ?? minimum,
                    disabledReason: getMinLevelDisabledReason(
                        inherited_access_level,
                        inherited_access_level_reason,
                        minimum,
                        'project'
                    ),
                })
            },
        ],
        projectDisabledReason: [
            (s) => [s.loading, s.canEdit, s.isOrgAdmin],
            (loading, canEdit, isOrgAdmin) => {
                if (loading) {
                    return 'Loading...'
                }
                if (!canEdit) {
                    return 'Cannot edit'
                }
                if (isOrgAdmin) {
                    return 'User is an organization admin'
                }
                return undefined
            },
        ],

        // Resource access level
        isResourceLevelShowingInherited: [
            (s) => [s.formResourceLevels, s.entry],
            (formResourceLevels, entry) => (resource: APIScopeObject) => {
                const resourceEntry = entry.resources[resource] as EffectiveAccessControlEntry
                return (
                    formResourceLevels[resource] === resourceEntry.inherited_access_level &&
                    resourceEntry.inherited_access_level !== null
                )
            },
        ],
        resourceInheritedReasonTooltip: [
            (s) => [s.isResourceLevelShowingInherited, s.entry],
            (isResourceLevelShowingInherited, entry) => (resource: APIScopeObject) =>
                isResourceLevelShowingInherited(resource)
                    ? getInheritedReasonTooltip(
                          (entry.resources[resource] as EffectiveAccessControlEntry).inherited_access_level_reason
                      )
                    : undefined,
        ],
        resourceLevelOptions: [
            (s) => [s.availableResourceLevels, s.entry, s.formResourceLevels],
            (availableResourceLevels, entry, formResourceLevels) =>
                (resource: APIScopeObject, resourceLabel: string) => {
                    const { access_level, inherited_access_level, inherited_access_level_reason, minimum, maximum } =
                        entry.resources[resource] as EffectiveAccessControlEntry
                    const levelOptions = getLevelOptionsForResource(availableResourceLevels, {
                        minimum: inherited_access_level ?? minimum,
                        maximum: maximum,
                        disabledReason: getMinLevelDisabledReason(
                            inherited_access_level,
                            inherited_access_level_reason,
                            minimum,
                            resourceLabel
                        ),
                    })
                    // Show "No override" option when there's no inherited level and the user has set an override
                    const hasFormOverride = formResourceLevels[resource] !== null
                    const hasSavedOverride = access_level !== null && formResourceLevels[resource] !== null
                    if (inherited_access_level === null && (hasSavedOverride || hasFormOverride)) {
                        return [
                            {
                                value: null as AccessControlLevel | null,
                                label: 'No override',
                                disabledReason: undefined,
                            },
                            ...levelOptions,
                        ]
                    }
                    return levelOptions
                },
        ],
        showResourceAddOverrideButton: [
            (s) => [s.formResourceLevels],
            (formResourceLevels) => (resource: APIScopeObject) => formResourceLevels[resource] === null,
        ],
    }),

    listeners(({ actions, values }) => ({
        clearResourceOverrides: () => {
            const clearedLevels = Object.fromEntries(
                Object.entries(values.entry.resources).map(([key, data]) => [
                    key,
                    (data as EffectiveAccessControlEntry).inherited_access_level,
                ])
            ) as Record<APIScopeObject, FormAccessLevel>
            actions.setResourceLevels(clearedLevels)
        },
        close: () => {
            actions.closeRuleModal()
        },
        save: () => {
            actions.saveGroupedRules({
                scopeType: values.scopeType,
                scopeId: values.entryId,
                projectLevel: values.formProjectLevel,
                resourceLevels: values.formResourceLevels,
            })
        },
    })),
])
