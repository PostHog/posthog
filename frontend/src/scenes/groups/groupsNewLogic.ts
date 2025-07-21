import { actions, beforeUnmount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { actionToUrl } from 'kea-router'
import api from 'lib/api'

import type { groupsNewLogicType } from './groupsNewLogicType'
import { forms } from 'kea-forms'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { CreateGroupParams, Group, GroupTypeIndex, Breadcrumb } from '~/types'
import { urls } from 'scenes/urls'
import { groupsModel } from '~/models/groupsModel'
import { Scene } from 'scenes/sceneTypes'
import { capitalizeFirstLetter } from 'lib/utils'

export type GroupsNewLogicProps = {
    groupTypeIndex: number
}

export interface NewGroupFormData {
    name: string
    group_key: string
    group_type_index: number
    properties: Record<string, any>
}

export interface GroupProperty {
    name: string
    value: string
}

const NEW_GROUP = {} as NewGroupFormData

export const groupsNewLogic = kea<groupsNewLogicType>([
    props({} as GroupsNewLogicProps),
    key((props) => `${props.groupTypeIndex}-new`),
    path((key) => ['scenes', 'groupsNew', 'groupsNewLogic', key]),

    connect(() => ({ values: [groupsModel, ['aggregationLabel']] })),

    selectors({
        logicProps: [() => [(_, props) => props], (props): GroupsNewLogicProps => props],
        groupTypeName: [
            (s) => [s.aggregationLabel, s.logicProps],
            (aggregationLabel, logicProps): string => {
                return aggregationLabel(logicProps.groupTypeIndex).singular
            },
        ],
        breadcrumbs: [
            (s) => [s.logicProps, s.groupTypeName],
            (logicProps, groupTypeName): Breadcrumb[] => {
                return [
                    {
                        key: Scene.PersonsManagement,
                        name: 'People',
                        path: urls.persons(),
                    },
                    {
                        key: Scene.Groups,
                        name: capitalizeFirstLetter(groupTypeName),
                        path: urls.groups(logicProps.groupTypeIndex),
                    },
                    {
                        key: Scene.GroupsNew,
                        name: `Create ${groupTypeName}`,
                    },
                ]
            },
        ],
    }),

    actions({
        saveGroup: (groupParams: CreateGroupParams) => ({ groupParams }),
        addProperty: () => ({}),
        removeProperty: (index: number) => ({ index }),
        updateProperty: (index: number, field: 'name' | 'value', value: string) => ({ index, field, value }),
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
                addProperty: (state) => [...state, { name: '', value: '' }],
                removeProperty: (state, { index }) => state.filter((_, i) => i !== index),
                updateProperty: (state, { index, field, value }) =>
                    state.map((prop, i) => (i === index ? { ...prop, [field]: value } : prop)),
                resetGroup: () => [],
            },
        ],
    }),

    forms(({ actions, props, values }) => ({
        group: {
            defaults: NEW_GROUP,
            errors: ({ group_key, name }: NewGroupFormData) => {
                return {
                    name: !name?.trim() ? 'Group name cannot be empty' : undefined,
                    group_key: !group_key?.trim() ? 'Group key cannot be empty' : undefined,
                }
            },
            submit: (formData: NewGroupFormData) => {
                const flattenedCustomProperties = flattenProperties(values.customProperties)
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
    })),

    actionToUrl(({ values }) => ({
        saveGroupSuccess: () => urls.groups(values.logicProps.groupTypeIndex),
    })),

    beforeUnmount(({ actions }) => actions.resetGroup()),
])

export function flattenProperties(properties: GroupProperty[]): Record<string, string> {
    return properties
        .filter((prop) => prop.name.trim() && prop.value.trim())
        .reduce((acc, prop) => {
            acc[prop.name.trim()] = prop.value
            return acc
        }, {} as Record<string, string>)
}
