import { actions, afterMount, beforeUnmount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
import { actionToUrl } from 'kea-router'
import { router } from 'kea-router'

import api from 'lib/api'
import { FEATURE_FLAGS } from 'lib/constants'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { capitalizeFirstLetter } from 'lib/utils'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { groupsModel } from '~/models/groupsModel'
import { Breadcrumb, CreateGroupParams, Group, GroupTypeIndex } from '~/types'

import type { groupsNewLogicType } from './groupsNewLogicType'

export type GroupsNewLogicProps = {
    groupTypeIndex: number
}

export interface NewGroupFormData {
    name: string
    group_key: string
    group_type_index: number
    customProperties: GroupProperty[]
}

export interface GroupProperty {
    name: string
    type: 'string' | 'boolean'
    value: string
}

const NEW_GROUP = {} as NewGroupFormData

export const groupsNewLogic = kea<groupsNewLogicType>([
    props({} as GroupsNewLogicProps),
    key((props) => `${props.groupTypeIndex}-new`),
    path((key) => ['scenes', 'groupsNew', 'groupsNewLogic', key]),

    connect(() => ({
        values: [groupsModel, ['aggregationLabel'], featureFlagLogic, ['featureFlags']],
    })),

    selectors({
        logicProps: [() => [(_, props) => props], (props): GroupsNewLogicProps => props],
        groupTypeName: [
            (s) => [s.aggregationLabel, s.logicProps],
            (aggregationLabel, logicProps): string => {
                return aggregationLabel(logicProps.groupTypeIndex).singular
            },
        ],
        groupTypeNamePlural: [
            (s) => [s.aggregationLabel, s.logicProps],
            (aggregationLabel, logicProps): string => {
                return aggregationLabel(logicProps.groupTypeIndex).plural
            },
        ],
        breadcrumbs: [
            (s) => [s.logicProps, s.groupTypeName],
            (logicProps, groupTypeName): Breadcrumb[] => {
                return [
                    {
                        key: Scene.Groups,
                        name: capitalizeFirstLetter(groupTypeName),
                        path: urls.groups(logicProps.groupTypeIndex),
                        iconType: 'group',
                    },
                    {
                        key: Scene.GroupsNew,
                        name: `Create ${groupTypeName}`,
                        iconType: 'group',
                    },
                ]
            },
        ],
    }),

    actions({
        saveGroup: (groupParams: CreateGroupParams) => ({ groupParams }),
        addFormProperty: () => ({}),
        removeFormProperty: (index: number) => ({ index }),
    }),

    reducers({
        createdGroup: [
            null as Group | null,
            {
                saveGroupSuccess: (_, { createdGroup }) => createdGroup,
                resetGroup: () => null,
            },
        ],
        customProperties: [
            [] as GroupProperty[],
            {
                addProperty: (state) => [...state, { name: '', type: 'string' as const, value: '' }],
                removeProperty: (state, { index }) => state.filter((_, i) => i !== index),
                updateProperty: (state, { index, field, value }) =>
                    state.map((prop, i) => (i === index ? { ...prop, [field]: value } : prop)),
                resetGroup: () => [],
            },
        ],
    }),

    forms(({ actions, props }) => ({
        group: {
            defaults: NEW_GROUP,
            errors: ({ group_key, name, customProperties }: NewGroupFormData) => {
                const errors: Record<string, string | object | undefined> = {
                    name: !name?.trim() ? 'Group name cannot be empty' : undefined,
                    group_key: !group_key?.trim() ? 'Group key cannot be empty' : undefined,
                }

                if (customProperties && customProperties.length > 0) {
                    const customPropertyErrors: any[] = []
                    let hasCustomPropertyErrors = false

                    customProperties.forEach((prop, index) => {
                        const propertyErrors: any = {}

                        if (!prop?.name?.trim()) {
                            propertyErrors.name = 'Property name cannot be empty'
                            hasCustomPropertyErrors = true
                        }

                        const duplicateIndex = customProperties.findIndex(
                            (p, i) => i !== index && p?.name?.trim() === prop?.name?.trim()
                        )
                        if (duplicateIndex !== -1 && prop?.name?.trim()) {
                            propertyErrors.name = 'Property name must be unique'
                            hasCustomPropertyErrors = true
                        }

                        // Check for reserved property name 'name'
                        if (prop?.name?.trim().toLowerCase() === 'name') {
                            propertyErrors.name = 'Property name "name" is reserved'
                            hasCustomPropertyErrors = true
                        }

                        customPropertyErrors[index] = propertyErrors
                    })

                    if (hasCustomPropertyErrors) {
                        errors.customProperties = customPropertyErrors
                    }
                }

                return errors
            },
            submit: (formData: NewGroupFormData) => {
                const flattenedCustomProperties = flattenProperties(formData.customProperties || [])
                const group_properties = {
                    name: formData.name,
                    ...flattenedCustomProperties,
                }

                const groupData: CreateGroupParams = {
                    group_key: formData.group_key,
                    group_type_index: props.groupTypeIndex as GroupTypeIndex,
                    group_properties,
                }
                actions.saveGroup(groupData)
            },
        },
    })),

    loaders(() => ({
        createdGroup: [
            null as Group | null,
            {
                saveGroup: async ({ groupParams }): Promise<Group> => {
                    try {
                        const newGroup = await api.groups.create(groupParams)
                        lemonToast.success('Group saved')
                        return newGroup
                    } catch (error) {
                        lemonToast.error('Failed to save group')
                        throw error
                    }
                },
            },
        ],
    })),

    listeners(({ actions, values }) => ({
        submitGroup: () => {
            if (values.groupHasErrors) {
                lemonToast.error('There was an error submitting this group. Make sure all fields are filled correctly.')
            }
        },
        saveGroupSuccess: () => actions.resetGroup(),
        addFormProperty: () => {
            const currentProperties = values.group.customProperties || []
            actions.setGroupValue('customProperties', [
                ...currentProperties,
                { name: '', type: 'string' as const, value: '' },
            ])
        },
        removeFormProperty: ({ index }) => {
            const currentProperties = values.group.customProperties || []
            actions.setGroupValue(
                'customProperties',
                currentProperties.filter((_, i) => i !== index)
            )
        },
    })),

    actionToUrl(({ values }) => ({
        saveGroupSuccess: () => urls.groups(values.logicProps.groupTypeIndex),
    })),

    afterMount(({ props, values }) => {
        // Redirect if the CRM feature flag is not enabled
        if (!values.featureFlags[FEATURE_FLAGS.CRM_ITERATION_ONE]) {
            router.actions.push(urls.groups(props.groupTypeIndex))
        }
    }),

    beforeUnmount(({ actions }) => actions.resetGroup()),
])

export function flattenProperties(properties: GroupProperty[]): Record<string, any> {
    return properties
        .filter((prop) => prop.name.trim() && prop.value.trim())
        .reduce(
            (acc, prop) => {
                const key = prop.name.trim()
                let value: any = prop.value

                // Convert boolean type values to proper types
                if (prop.type === 'boolean') {
                    if (value === 'true') {
                        value = true
                    } else if (value === 'false') {
                        value = false
                    } else if (value === 'null') {
                        value = null
                    }
                } else if (prop.type === 'string') {
                    // Convert numeric strings to numbers
                    const numericValue = Number(value)
                    if (!isNaN(numericValue) && isFinite(numericValue) && value.trim() !== '') {
                        value = numericValue
                    }
                }

                acc[key] = value
                return acc
            },
            {} as Record<string, any>
        )
}
