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
                    // skip_create_notebook: this is a read-only display lookup; without it `groups/find`
                    // lazily creates the group's CRM notebook as a side effect.
                    const params = {
                        group_type_index: props.groupTypeIndex,
                        group_key: props.groupKey,
                        skip_create_notebook: true,
                    }
                    try {
                        // `groups/find` is a cross-product (groups) endpoint with no conversations-generated client.
                        // nosemgrep: prefer-codegen-api
                        return await api.get(`api/projects/${values.currentTeamId}/groups/find?${toParams(params)}`)
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
