import { kea, connect, path, key, props, reducers, actions, selectors, listeners, afterMount } from 'kea'
import api, { CountedPaginatedResponse } from 'lib/api'
import { ActorType } from '~/types'
import { loaders } from 'kea-loaders'
import { cohortsModel } from '~/models/cohortsModel'
import { lemonToast } from '@posthog/lemon-ui'
import { router, urlToAction } from 'kea-router'
import { urls } from 'scenes/urls'

import type { personsModalLogicType } from './personsModalV2LogicType'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { fromParamsGivenUrl, isGroupType } from 'lib/utils'
import { groupsModel } from '~/models/groupsModel'

export interface PersonModalLogicProps {
    url: string
    closeModal?: () => void
}

export const personsModalLogic = kea<personsModalLogicType>([
    path(['scenes', 'trends', 'personsModalLogicV2']),
    props({} as PersonModalLogicProps),
    key((props) => `${props.url}` || ''),
    actions({
        setSearchTerm: (search: string) => ({ search }),
        saveCohortWithUrl: (cohortName: string) => ({ cohortName }),
        resetActors: () => true,
    }),
    connect({
        values: [groupsModel, ['groupTypes', 'aggregationLabel']],
        actions: [eventUsageLogic, ['reportCohortCreatedFromPersonsModal']],
    }),

    loaders(({ values, actions }) => ({
        actorsResponse: [
            null as CountedPaginatedResponse<ActorType> | null,
            {
                loadActors: async ({ url, clear = false }: { url: string; clear?: boolean }) => {
                    url += '&include_recordings=true'

                    if (values.searchTerm) {
                        url += `&search=${values.searchTerm}`
                    }

                    const res = await api.get(url)

                    const payload: CountedPaginatedResponse<ActorType> = {
                        total_count: res?.results[0]?.count || 0,
                        results: res?.results[0]?.people,
                        next: res?.next,
                    }

                    if (clear) {
                        actions.resetActors()
                    }
                    return payload
                },
            },
        ],
    })),

    reducers(() => ({
        actors: [
            [] as ActorType[],
            {
                loadActorsSuccess: (state, { actorsResponse }) => {
                    console.log({ actorsResponse })
                    return [...state, ...(actorsResponse?.results || [])]
                },
                resetActors: () => [],
            },
        ],
        searchTerm: [
            '',
            {
                setSearchTerm: (_, { search }) => search,
            },
        ],
    })),

    listeners(({ actions, props }) => ({
        setSearchTerm: async ({}, breakpoint) => {
            await breakpoint(500)
            actions.loadActors({ url: props.url, clear: true })
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

            const filters = fromParamsGivenUrl('?' + qs)
            actions.reportCohortCreatedFromPersonsModal(filters)
        },
    })),

    selectors({
        actorLabel: [
            (s) => [s.actors, s.aggregationLabel],
            (actors, aggregationLabel) => {
                const firstResult = actors[0]

                if (!firstResult) {
                    return { singular: 'result', plural: 'results' }
                }
                return aggregationLabel(isGroupType(firstResult) ? firstResult.group_type_index : undefined)
            },
        ],
    }),

    afterMount(({ actions, props }) => {
        actions.loadActors({ url: props.url })
    }),

    urlToAction(({ props, cache }) => ({
        '*': (_a, _b, _c, { pathname }) => {
            if (!cache['lastPathname']) {
                cache['lastPathname'] = pathname
                return
            }
            // If we click anything that navigates us away, close the modal but allowing for changes in hash
            if (cache['lastPathname'] !== pathname) {
                props.closeModal?.()
            }
        },
    })),
])
