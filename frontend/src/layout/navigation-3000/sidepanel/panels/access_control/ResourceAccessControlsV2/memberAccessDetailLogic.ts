import { afterMount, kea, key, path, props } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'

import type { memberAccessDetailLogicType } from './memberAccessDetailLogicType'

export interface MemberObjectOverride {
    resource: string
    resource_id: string
    name: string
    access_level: string
    source: 'member' | 'role' | 'default'
    role_name: string | null
}

export interface MemberPropertyRestriction {
    property: string
    property_type: 'person' | 'event'
    access_level: string
    source: 'member' | 'role' | 'default'
    role_name: string | null
}

export interface MemberAccessDetailLogicProps {
    projectId: string
    membershipId: string
}

export const memberAccessDetailLogic = kea<memberAccessDetailLogicType>([
    path((key) => ['scenes', 'access_control', 'memberAccessDetailLogic', key]),
    props({} as MemberAccessDetailLogicProps),
    key((props) => `${props.projectId}:${props.membershipId}`),

    loaders(({ props }) => ({
        objects: [
            [] as MemberObjectOverride[],
            {
                loadObjects: async () => {
                    const response = await api.get<{ results: MemberObjectOverride[] }>(
                        `api/projects/${props.projectId}/access_control_member_objects?member_id=${props.membershipId}`
                    )
                    return response.results
                },
            },
        ],
        properties: [
            [] as MemberPropertyRestriction[],
            {
                loadProperties: async () => {
                    const response = await api.get<{ results: MemberPropertyRestriction[] }>(
                        `api/projects/${props.projectId}/access_control_member_properties?member_id=${props.membershipId}`
                    )
                    return response.results
                },
            },
        ],
    })),

    afterMount(({ actions }) => {
        actions.loadObjects()
        actions.loadProperties()
    }),
])
