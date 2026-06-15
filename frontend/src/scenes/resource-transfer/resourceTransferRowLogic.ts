import { actions, connect, kea, key, path, props, reducers } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'

import { type ResourceTransferLogicProps, type SearchResponse, resourceTransferLogic } from './resourceTransferLogic'
import type { resourceTransferRowLogicType } from './resourceTransferRowLogicType'

export interface ResourceTransferRowLogicProps {
    resourceKey: string
    transferLogicProps: ResourceTransferLogicProps
}

export const resourceTransferRowLogic = kea<resourceTransferRowLogicType>([
    path(['scenes', 'resource-transfer', 'resourceTransferRowLogic']),
    props({} as ResourceTransferRowLogicProps),
    key((props) => props.resourceKey),
    connect((props: ResourceTransferRowLogicProps) => ({
        values: [resourceTransferLogic(props.transferLogicProps), ['destinationTeamId', 'currentOrganization']],
    })),
    actions({
        setIsSearching: (isSearching: boolean) => ({ isSearching }),
        searchResources: (resourceKind: string, query: string) => ({ resourceKind, query }),
    }),
    reducers({
        isSearching: [
            false,
            {
                setIsSearching: (_, { isSearching }) => isSearching,
            },
        ],
    }),
    loaders(({ values }) => ({
        searchResults: [
            null as SearchResponse | null,
            {
                searchResources: async ({ resourceKind, query }) => {
                    const { destinationTeamId, currentOrganization } = values
                    if (!destinationTeamId || !currentOrganization) {
                        throw new Error('Missing required fields for search')
                    }

                    return await api.create<SearchResponse>(
                        `api/organizations/${currentOrganization.id}/resource_transfers/search/`,
                        {
                            team_id: destinationTeamId,
                            resource_kind: resourceKind,
                            q: query,
                        }
                    )
                },
            },
        ],
    })),
])
