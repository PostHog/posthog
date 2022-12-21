import { kea, connect, path, key, props, reducers, actions, selectors, listeners, afterMount } from 'kea'
import api from 'lib/api'
import { ActorType, PropertiesTimelineFilterType } from '~/types'
import { loaders } from 'kea-loaders'
import { cohortsModel } from '~/models/cohortsModel'
import { lemonToast } from '@posthog/lemon-ui'
import { router, urlToAction } from 'kea-router'
import { urls } from 'scenes/urls'

import type { personsModalLogicType } from './personsModalLogicType'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { fromParamsGivenUrl, isGroupType } from 'lib/utils'
import { groupsModel } from '~/models/groupsModel'

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
    path(['scenes', 'trends', 'personsModalLogic']),
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
        missingActorsCount: [
            0,
            {
                loadActorsSuccess: (state, { actorsResponse }) => state + (actorsResponse?.missing_persons || 0),
                resetActors: () => 0,
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
        propertiesTimelineFilterFromUrl: [
            (_, p) => [p.url],
            (url): PropertiesTimelineFilterType => {
                // PersonsModal fully relies on the actors URLs received with insight results, so we need to parse
                // filters out of that URL
                const params = new URLSearchParams(url.split('?')[1])
                const properties: PropertiesTimelineFilterType = {
                    date_from: params.get('date_from'),
                    date_to: params.get('date_to'),
                    events: params.has('events') ? JSON.parse(params.get('events') as string) : undefined,
                    actions: params.has('actions') ? JSON.parse(params.get('actions') as string) : undefined,
                    properties: params.has('properties') ? JSON.parse(params.get('properties') as string) : undefined,
                    aggregation_group_type_index: params.has('aggregation_group_type_index')
                        ? parseInt(params.get('aggregation_group_type_index') as string)
                        : undefined,
                }
                return properties
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
