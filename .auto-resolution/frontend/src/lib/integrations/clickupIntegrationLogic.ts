import { actions, kea, key, path, props } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'

import type { clickupIntegrationLogicType } from './clickupIntegrationLogicType'

export const clickupIntegrationLogic = kea<clickupIntegrationLogicType>([
    props({} as { id: number }),
    key((props) => props.id),
    path((key) => ['lib', 'integrations', 'clickupIntegrationLogic', key]),
    actions({
        loadClickUpLists: (spaceId: string) => ({ spaceId }),
        loadClickUpSpaces: (workspaceId: string) => ({ workspaceId }),
        loadClickUpWorkspaces: true,
    }),
    loaders(({ props }) => ({
        clickUpSpaces: [
            null as { id: string; name: string }[] | null,
            {
                loadClickUpSpaces: async ({ workspaceId }) => {
                    const res = await api.integrations.clickUpSpaces(props.id, workspaceId)
                    return res.spaces
                },
            },
        ],
        clickUpLists: [
            null as { id: string; name: string }[] | null,
            {
                loadClickUpLists: async ({ spaceId }) => {
                    const res = await api.integrations.clickUpLists(props.id, spaceId)
                    return res.lists
                },
            },
        ],
        clickUpWorkspaces: [
            null as { id: string; name: string }[] | null,
            {
                loadClickUpWorkspaces: async () => {
                    const res = await api.integrations.clickUpWorkspaces(props.id)
                    return res.workspaces
                },
            },
        ],
    })),
])
