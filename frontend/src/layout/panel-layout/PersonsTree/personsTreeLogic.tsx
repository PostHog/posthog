import { afterMount, connect, kea, path, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import api, { CountedPaginatedResponse } from 'lib/api'
import { rankPersons } from 'lib/components/CommandBar/searchBarLogic'

import { PersonType, SearchableEntity, SearchResponse } from '~/types'

import { panelLayoutLogic } from '../panelLayoutLogic'
import type { personsTreeLogicType } from './personsTreeLogicType'

export const personsTreeLogic = kea<personsTreeLogicType>([
    path(['layout', 'panel-layout', 'personsTreeLogic']),
    connect(() => ({
        values: [panelLayoutLogic, ['searchTerm']],
    })),
    loaders(({ values }) => ({
        rawSearchResponse: [
            null as SearchResponse | null,
            {
                loadSearchResponse: async (_, breakpoint) => {
                    const response = await api.search.list({
                        q: values.searchTerm,
                        entities: ['person' as SearchableEntity],
                    })

                    breakpoint()
                    return response
                },
            },
        ],
        rawPersonsResponse: [
            null as CountedPaginatedResponse<PersonType> | null,
            {
                loadPersonsResponse: async () => {
                    const response = await api.persons.list({ search: values.searchTerm })
                    return response
                },
            },
        ],
    })),
    selectors({
        personsResults: [
            (s) => [s.rawSearchResponse, s.rawPersonsResponse, s.searchTerm],
            (searchResponse, personsResponse, query) => {
                if (!searchResponse && !personsResponse) {
                    return null
                }

                return [
                    ...(searchResponse ? searchResponse.results : []),
                    ...(personsResponse ? rankPersons(personsResponse.results, query) : []),
                ].sort((a, b) => (a.rank && b.rank ? a.rank - b.rank : 1))
            },
        ],
    }),
    afterMount(({ actions }) => {
        actions.loadPersonsResponse()
    }),
])
