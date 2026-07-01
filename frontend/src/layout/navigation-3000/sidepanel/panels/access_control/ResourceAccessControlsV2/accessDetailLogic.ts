import { afterMount, kea, key, path, props } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'

import type { accessDetailLogicType } from './accessDetailLogicType'

export type AccessScope = 'member' | 'role'

export interface AccessObjectOverride {
    resource: string
    resource_id: string
    name: string
    access_level: string
    source: 'member' | 'role' | 'default'
    role_name: string | null
}

export interface AccessPropertyRestriction {
    property: string
    property_type: 'person' | 'event'
    access_level: string
    source: 'member' | 'role' | 'default'
    role_name: string | null
}

export interface AccessDetailLogicProps {
    projectId: string
    scopeType: AccessScope
    subjectId: string
}

function endpoint(props: AccessDetailLogicProps, kind: 'objects' | 'properties'): string {
    const base = `api/projects/${props.projectId}`
    if (props.scopeType === 'role') {
        return `${base}/access_control_role_${kind}?role_id=${props.subjectId}`
    }
    return `${base}/access_control_member_${kind}?member_id=${props.subjectId}`
}

export const accessDetailLogic = kea<accessDetailLogicType>([
    path((key) => ['scenes', 'access_control', 'accessDetailLogic', key]),
    props({} as AccessDetailLogicProps),
    key((props) => `${props.projectId}:${props.scopeType}:${props.subjectId}`),

    loaders(({ props }) => ({
        objects: [
            [] as AccessObjectOverride[],
            {
                loadObjects: async () =>
                    (await api.get<{ results: AccessObjectOverride[] }>(endpoint(props, 'objects'))).results,
            },
        ],
        properties: [
            [] as AccessPropertyRestriction[],
            {
                loadProperties: async () =>
                    (await api.get<{ results: AccessPropertyRestriction[] }>(endpoint(props, 'properties'))).results,
            },
        ],
    })),

    afterMount(({ actions }) => {
        actions.loadObjects()
        actions.loadProperties()
    }),
])
