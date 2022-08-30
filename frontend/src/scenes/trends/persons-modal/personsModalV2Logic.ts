import { kea, connect, path, key, props, reducers, actions, selectors, listeners, afterMount } from 'kea'
import api, { CountedPaginatedResponse } from 'lib/api'
import { ActorType } from '~/types'
import { loaders } from 'kea-loaders'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'
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
    }),
    connect({
        values: [groupsModel, ['groupTypes', 'aggregationLabel'], featureFlagLogic, ['featureFlags']],
        actions: [eventUsageLogic, ['reportCohortCreatedFromPersonsModal']],
    }),

    loaders(({ values }) => ({
        people: [
            null as CountedPaginatedResponse<ActorType> | null,
            {
                loadPeople: async ({ url, search, clear }: { url: string; search?: string; clear?: boolean }) => {
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

            const filters = fromParamsGivenUrl('?' + qs)
            actions.reportCohortCreatedFromPersonsModal(filters)
        },
    })),

    selectors({
        allPeople: [(s) => [s.people], (res: CountedPaginatedResponse<ActorType> | null) => res?.results],
        isGroupType: [(s) => [s.people], (people) => people?.results?.[0] && isGroupType(people?.results[0])],
        actorLabel: [
            (s) => [s.people, s.isGroupType, s.groupTypes, s.aggregationLabel],
            (result, _isGroupType, groupTypes, aggregationLabel) => {
                if (_isGroupType) {
                    return 'groups'
                    // return result?.action?.math_group_type_index != undefined &&
                    //     groupTypes.length > result?.action.math_group_type_index
                    //     ? aggregationLabel(result?.action.math_group_type_index).plural
                    //     : ''
                } else {
                    return 'persons'
                }
            },
        ],
    }),

    afterMount(({ actions, props }) => {
        actions.loadPeople({ url: props.url, clear: true })
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
