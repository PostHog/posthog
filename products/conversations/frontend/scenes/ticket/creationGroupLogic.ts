import { afterMount, connect, kea, key, path, props } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { toParams } from 'lib/utils/url'
import { teamLogic } from 'scenes/teamLogic'

import { Group } from '~/types'

import type { creationGroupLogicType } from './creationGroupLogicType'

export type CreationGroupLogicProps = {
    groupTypeIndex: number | null
    groupKey: string | null
}

// Fetches the group a ticket was created with (its organization_id snapshot) so the related-groups
// panel can show its name and a working link even when it has dropped out of the live related list.
export const creationGroupLogic = kea<creationGroupLogicType>([
    props({} as CreationGroupLogicProps),
    key((props) => `${props.groupTypeIndex}-${props.groupKey}`),
    path((key) => ['products', 'conversations', 'frontend', 'scenes', 'ticket', 'creationGroupLogic', key]),
    connect(() => ({
        values: [teamLogic, ['currentTeamId']],
    })),
    loaders(({ values, props }) => ({
        group: [
            null as Group | null,
            {
                loadGroup: async () => {
                    if (props.groupTypeIndex === null || !props.groupKey) {
                        return null
                    }
                    const params = { group_type_index: props.groupTypeIndex, group_key: props.groupKey }
                    try {
                        return await api.get(`api/environments/${values.currentTeamId}/groups/find?${toParams(params)}`)
                    } catch {
                        // Group may no longer exist (stale snapshot) — degrade to no row rather than a broken link.
                        return null
                    }
                },
            },
        ],
    })),
    afterMount(({ actions }) => {
        actions.loadGroup()
    }),
])
