import { kea, connect, path, key, props, reducers, actions, selectors, listeners, afterMount } from 'kea'
import api from 'lib/api'
import { ActorType } from '~/types'
import { loaders } from 'kea-loaders'
import { cohortsModel } from '~/models/cohortsModel'
import { lemonToast } from '@posthog/lemon-ui'
import { router, urlToAction } from 'kea-router'
import { urls } from 'scenes/urls'

import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { fromParamsGivenUrl, isGroupType } from 'lib/utils'
import { groupsModel } from '~/models/groupsModel'

import type { personsModalLogicType } from './personsModalLogicType'

export interface PersonModalLogicProps {
    url: string
}

export interface ListActorsResponse {
    results: {
        count: number
        people: ActorType[]
    }[]
    missing_persons?: number
    next?: string
}

export const personsModalLogic = kea<personsModalLogicType>([
    path(['scenes', 'trends', 'personsModalLogicV2']),
    props({} as PersonModalLogicProps),
    key((props) => props.url),
    actions({
        setSearchTerm: (search: string) => ({ search }),
        saveCohortWithUrl: (cohortName: string) => ({ cohortName }),
        resetActors: () => true,
        closeModal: () => true,
        setIsCohortModalOpen: (isOpen: boolean) => ({ isOpen }),
    }),
    connect({
        values: [groupsModel, ['groupTypes', 'aggregationLabel']],
        actions: [eventUsageLogic, ['reportCohortCreatedFromPersonsModal', 'reportPersonsModalViewed']],
    }),

    loaders(({ values, actions }) => ({
        actorsResponse: [
            null as ListActorsResponse | null,
            {
                loadActors: async ({ url, clear }: { url: string; clear?: boolean }) => {
                    url += '&include_recordings=true'

                    if (values.searchTerm) {
                        url += `&search=${values.searchTerm}`
                    }

                    const res = await api.get(url)

                    if (clear) {
                        actions.resetActors()
                    }
                    return res
                },
            },
        ],
    })),

    reducers(() => ({
        actors: [
            [] as ActorType[],
            {
                loadActorsSuccess: (state, { actorsResponse }) => [
                    ...state,
                    ...(actorsResponse?.results?.[0]?.people || []),
                ],
                resetActors: () => [],
            },
        ],
        searchTerm: [
            '',
            {
                setSearchTerm: (_, { search }) => search,
            },
        ],
        isModalOpen: [
            true,
            {
                closeModal: () => false,
            },
        ],
        isCohortModalOpen: [
            false,
            {
                setIsCohortModalOpen: (_, { isOpen }) => isOpen,
                closeModal: () => false,
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
            actions.setIsCohortModalOpen(false)
            actions.reportCohortCreatedFromPersonsModal(filters)
        },
    })),

    selectors({
        actorType: [
            (s) => [s.actors],
            (actors) => {
                const firstResult = actors[0]

                return firstResult?.type
            },
        ],
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

        actions.reportPersonsModalViewed({
            url: props.url,
            // TODO: parse qs
        })
    }),

    urlToAction(({ cache, actions }) => ({
        '*': (_a, _b, _c, { pathname }) => {
            if (!cache['lastPathname']) {
                cache['lastPathname'] = pathname
                return
            }
            // If we click anything that navigates us away, close the modal but
            // allowing for changes in hash due to the SessionsRecordings Modal
            if (cache['lastPathname'] !== pathname) {
                actions.closeModal()
            }
        },
    })),
])
