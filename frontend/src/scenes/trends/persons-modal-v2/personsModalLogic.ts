import { kea, connect, path, key, props, reducers, actions, selectors, listeners, afterMount } from 'kea'
import api, { CountedPaginatedResponse } from 'lib/api'
import { ActorType } from '~/types'
import type { personsModalLogicType } from './personsModalLogicType'
import { loaders } from 'kea-loaders'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { cohortsModel } from '~/models/cohortsModel'
import { lemonToast } from '@posthog/lemon-ui'
import { router } from 'kea-router'
import { urls } from 'scenes/urls'

export interface PersonModalLogicProps {
    url: string
}

export const personsModalLogic = kea<personsModalLogicType>([
    path(['scenes', 'trends', 'personsModalLogicV2']),
    props({} as PersonModalLogicProps),
    key((props) => `${props.url}` || ''),
    actions({
        setSearchTerm: (search: string) => ({ search }),
        saveCohortWithUrl: (cohortName: string) => ({ cohortName }),
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
                        url += '&include_recordings=true'
                    }

                    if (search) {
                        url += `&search=${search}`
                    }

                    const res = await api.get(url)

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
        saveCohortWithUrl: async ({ cohortName }) => {
            const cohortParams = {
                is_static: true,
                name: cohortName,
            }

            const qs = props.url.split('?').pop() || ''
            const cohort = await api.create('api/cohort?' + qs, cohortParams)
            cohortsModel.actions.cohortCreated(cohort)
            lemonToast.success('Cohort saved', {
                toastId: `cohort-saved-${cohort.id}`,
                button: {
                    label: 'View cohort',
                    action: () => router.actions.push(urls.cohort(cohort.id)),
                },
            })

            // const filters = fromParamsGivenUrl('?' + qs) // this function expects the question mark to be included
            // actions.reportCohortCreatedFromPersonsModal(filters)
        },
    })),

    selectors({
        allPeople: [(s) => [s.people], (res) => res?.results],
    }),

    afterMount(({ actions, props }) => {
        actions.loadPeople({ url: props.url, clear: true })
    }),
])
