import { actions, kea, path, props, reducers } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import { Group } from '~/types'

import type { groupDeleteModalLogicType } from './groupDeleteModalLogicType'

export type GroupPartial = Pick<Group, 'group_type_index' | 'group_key'>
export interface GroupDeleteModalLogicProps {
    group: GroupPartial
}

export type GroupDeleteCallback = (group: GroupPartial) => void

export const groupDeleteModalLogic = kea<groupDeleteModalLogicType>([
    path(['scenes', 'groups', 'groupDeleteModalLogic']),
    props({} as GroupDeleteModalLogicProps),
    actions({
        showGroupDeleteModal: (group: GroupPartial | null, callback?: GroupDeleteCallback) => ({
            group,
            callback,
        }),
        deleteGroup: (group: GroupPartial) => ({ group }),
    }),
    reducers({
        groupDeleteModal: [
            null as GroupPartial | null,
            {
                showGroupDeleteModal: (_, { group }) => group,
            },
        ],
        groupDeleteCallback: [
            null as GroupDeleteCallback | null,
            {
                showGroupDeleteModal: (_, { callback }) => callback ?? null,
            },
        ],
    }),
    loaders(({ actions, values }) => ({
        deletedGroup: [
            null as GroupPartial | null,
            {
                deleteGroup: async ({ group }, breakpoint) => {
                    await api.delete(
                        `api/projects/@current/groups/delete_group?group_type_index=${
                            group.group_type_index
                        }&group_key=${encodeURIComponent(group.group_key)}`
                    )
                    await breakpoint(500)
                    lemonToast.success(
                        <>
                            The group <strong>{group.group_key}</strong> was removed from the project.
                        </>
                    )
                    values.groupDeleteCallback?.(group)
                    actions.showGroupDeleteModal(null)
                    return group
                },
            },
        ],
    })),
])
