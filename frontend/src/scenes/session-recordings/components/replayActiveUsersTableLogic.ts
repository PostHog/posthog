import { defaults, kea, key, path, props } from 'kea'
import { lazyLoaders } from 'kea-loaders'

import api from 'lib/api'

import { NodeKind, ReplayActiveUsersQuery } from '~/queries/schema/schema-general'
import { PersonType } from '~/types'

import type { replayActiveUsersTableLogicType } from './replayActiveUsersTableLogicType'

export interface ReplayActiveUsersTableLogicProps {
    scene?: 'templates' | 'filters' | 'replay-home'
}

export const replayActiveUsersTableLogic = kea<replayActiveUsersTableLogicType>([
    path(['scenes', 'session-recordings', 'components', 'replayActiveUsersTableLogic']),
    props({} as ReplayActiveUsersTableLogicProps),
    key((props) => props.scene || 'default'),
    defaults({
        countedUsers: [] as { person: PersonType; count: number }[],
    }),
    lazyLoaders(() => ({
        countedUsers: {
            loadCountedUsers: async (_, breakpoint): Promise<{ person: PersonType; count: number }[]> => {
                const query: ReplayActiveUsersQuery = {
                    kind: NodeKind.ReplayActiveUsersQuery,
                }

                const response = await api.query(query)

                breakpoint()

                return (response.results || []).map((result) => ({
                    person: {
                        id: result.person.id,
                        properties: result.person.properties,
                    } as PersonType,
                    count: result.count,
                }))
            },
        },
    })),
])
