import { kea, connect, path, key, props, reducers, actions, selectors, listeners, afterMount } from 'kea'
import api, { CountedPaginatedResponse } from 'lib/api'
import { ActorType } from '~/types'
import type { personsModalLogicType } from './personsModalLogicType'
import { loaders } from 'kea-loaders'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'

export interface PersonModalLogicProps {
    url: string
}

export const personsModalLogic = kea<personsModalLogicType>([
    path(['scenes', 'trends', 'personsModalLogicV2']),
    props({} as PersonModalLogicProps),
    key((props) => `${props.url}` || ''),
    actions({
        setSearchTerm: (search: string) => ({ search }),
    }),
    connect({
        values: [featureFlagLogic, ['featureFlags']],
    }),

    loaders(({ values }) => ({
        people: [
            null as CountedPaginatedResponse<ActorType> | null,
            {
                loadPeople: async ({
                    url,
                    search,
                    clear = false,
                }: {
                    url: string
                    search?: string
                    clear?: boolean
                }) => {
                    if (values.featureFlags[FEATURE_FLAGS.RECORDINGS_IN_INSIGHTS]) {
                        // A bit hacky (doesn't account for hash params),
                        // but it works and only needed while we have this feature flag
                        url += '&include_recordings=true'
                    }

                    if (search) {
                        url += `&search=${search}`
                    }

                    const res = await api.get(url)

                    await new Promise((r) => setTimeout(r, 2000))

                    const peopleList = clear
                        ? res?.results[0]?.people
                        : [...(values.people?.results || []), ...res?.results[0]?.people]

                    const payload: CountedPaginatedResponse<ActorType> = {
                        total_count: res?.results[0]?.count || 0,
                        results: peopleList,
                        next: res?.next,
                    }

                    return payload
                },
            },
        ],
    })),

    reducers(() => ({
        searchTerm: [
            '',
            {
                setSearchTerm: (_, { search }) => search,
            },
        ],
    })),

    listeners(({ actions, props }) => ({
        setSearchTerm: async ({ search }, breakpoint) => {
            await breakpoint(500)

            actions.loadPeople({ url: props.url, search, clear: true })
        },
    })),

    selectors({
        allPeople: [(s) => [s.people], (res) => res?.results],
    }),

    afterMount(({ actions, props }) => {
        actions.loadPeople({ url: props.url, clear: true })
    }),
])
