import { actions, connect, kea, key, listeners, path, props, reducers } from 'kea'
import { loaders } from 'kea-loaders'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'

import { AccessControlLevel } from '~/types'

import type { addObjectOverrideModalLogicType } from './addObjectOverrideModalLogicType'
import { memberAccessDetailLogic } from './memberAccessDetailLogic'

// Object resource types whose list `id` maps directly to their `/{route}/{id}/access_controls` endpoint.
export const ADD_RULE_RESOURCES: { value: string; label: string; route: string }[] = [
    { value: 'dashboard', label: 'Dashboard', route: 'dashboards' },
    { value: 'insight', label: 'Insight', route: 'insights' },
    { value: 'feature_flag', label: 'Feature flag', route: 'feature_flags' },
    { value: 'experiment', label: 'Experiment', route: 'experiments' },
    { value: 'survey', label: 'Survey', route: 'surveys' },
    { value: 'warehouse_table', label: 'Warehouse table', route: 'warehouse_tables' },
    { value: 'warehouse_view', label: 'Warehouse view', route: 'warehouse_saved_queries' },
]

export interface ObjectOption {
    id: string
    name: string
}

export interface AddObjectOverrideModalLogicProps {
    projectId: string
    membershipId: string
}

function routeFor(resource: string): string {
    return ADD_RULE_RESOURCES.find((r) => r.value === resource)?.route ?? `${resource}s`
}

export const addObjectOverrideModalLogic = kea<addObjectOverrideModalLogicType>([
    path((key) => ['scenes', 'access_control', 'addObjectOverrideModalLogic', key]),
    props({} as AddObjectOverrideModalLogicProps),
    key((props) => `${props.projectId}:${props.membershipId}`),

    connect((props: AddObjectOverrideModalLogicProps) => ({
        actions: [memberAccessDetailLogic(props), ['loadObjects']],
    })),

    actions({
        openModal: true,
        closeModal: true,
        setResource: (resource: string) => ({ resource }),
        setSearch: (search: string) => ({ search }),
        setObjectId: (objectId: string | null) => ({ objectId }),
        setLevel: (level: AccessControlLevel) => ({ level }),
        submitRule: true,
        deleteObjectOverride: (resource: string, resourceId: string) => ({ resource, resourceId }),
    }),

    reducers({
        isOpen: [false, { openModal: () => true, closeModal: () => false }],
        resource: ['dashboard', { setResource: (_, { resource }) => resource, closeModal: () => 'dashboard' }],
        search: ['', { setSearch: (_, { search }) => search, setResource: () => '', closeModal: () => '' }],
        objectId: [
            null as string | null,
            { setObjectId: (_, { objectId }) => objectId, setResource: () => null, closeModal: () => null },
        ],
        level: [
            AccessControlLevel.None as AccessControlLevel,
            { setLevel: (_, { level }) => level, closeModal: () => AccessControlLevel.None },
        ],
    }),

    loaders(({ props, values }) => ({
        objectOptions: [
            [] as ObjectOption[],
            {
                loadObjectOptions: async (_, breakpoint) => {
                    await breakpoint(300)
                    const route = routeForCurrent(values)
                    const response = await api.get<{ results: Record<string, any>[] }>(
                        `api/projects/${props.projectId}/${route}/?limit=20&search=${encodeURIComponent(values.search)}`
                    )
                    return response.results.map((item) => ({
                        id: String(item.id),
                        name: item.name || item.title || item.derived_name || item.key || String(item.id),
                    }))
                },
            },
        ],
    })),

    listeners(({ props, actions, values }) => ({
        openModal: () => actions.loadObjectOptions(null),
        setResource: () => actions.loadObjectOptions(null),
        setSearch: () => actions.loadObjectOptions(null),
        submitRule: async () => {
            if (!values.objectId) {
                return
            }
            try {
                await api.put(
                    `api/projects/${props.projectId}/${routeForCurrent(values)}/${values.objectId}/access_controls`,
                    { organization_member: props.membershipId, access_level: values.level }
                )
                lemonToast.success('Access rule added')
                actions.loadObjects()
                actions.closeModal()
            } catch (e) {
                const error = (e as Record<string, any>).detail || 'Failed to add access rule'
                lemonToast.error(error)
            }
        },
        deleteObjectOverride: async ({ resource, resourceId }) => {
            // Clearing the member override = PUT with a null access level for this member
            try {
                await api.put(`api/projects/${props.projectId}/${routeFor(resource)}/${resourceId}/access_controls`, {
                    organization_member: props.membershipId,
                    access_level: null,
                })
                lemonToast.success('Rule removed')
                actions.loadObjects()
            } catch (e) {
                const error = (e as Record<string, any>).detail || 'Failed to remove rule'
                lemonToast.error(error)
            }
        },
    })),
])

function routeForCurrent(values: { resource: string }): string {
    return routeFor(values.resource)
}
