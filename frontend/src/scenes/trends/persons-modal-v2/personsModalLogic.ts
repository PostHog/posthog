import { kea, path, key, props, selectors, afterMount } from 'kea'
import { router } from 'kea-router'
import api, { PaginatedResponse } from 'lib/api'
import { convertPropertiesToPropertyGroup, fromParamsGivenUrl, isGroupType, toParams } from 'lib/utils'
import {
    ActionFilter,
    FilterType,
    InsightType,
    FunnelVizType,
    FunnelCorrelationResultsType,
    ActorType,
    GraphDataset,
    ChartDisplayType,
    FilterLogicalOperator,
} from '~/types'
import type { personsModalLogicType } from './personsModalLogicType'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { TrendActors } from 'scenes/trends/types'
import { cleanFilters } from 'scenes/insights/utils/cleanFilters'
import { filterTrendsClientSideParams } from 'scenes/insights/sharedUtils'
import { FEATURE_FLAGS } from 'lib/constants'
import { cohortsModel } from '~/models/cohortsModel'
import { dayjs } from 'lib/dayjs'
import { groupsModel } from '~/models/groupsModel'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { lemonToast } from 'lib/components/lemonToast'
import { urls } from 'scenes/urls'
import { loaders } from 'kea-loaders'

export interface PersonModalLogicProps {
    url?: string
}

export const personsModalLogic = kea<personsModalLogicType>([
    path(['scenes', 'trends', 'personsModalLogicV2']),
    props({} as PersonModalLogicProps),
    key((props) => props.url || ''),

    loaders({
        people: [
            null as PaginatedResponse<ActorType> | null,
            {
                loadPeople: async (url: string) => {
                    // if (values.featureFlags[FEATURE_FLAGS.RECORDINGS_IN_INSIGHTS]) {
                    //     // A bit hacky (doesn't account for hash params),
                    //     // but it works and only needed while we have this feature flag
                    //     url += '&include_recordings=true'
                    // }

                    const res = await api.get(url)
                    return {
                        results: res?.results[0]?.people,
                        count: res?.results[0]?.count || 0,
                        next: res?.next,
                    }
                },
            },
        ],
    }),

    selectors({
        allPeople: [(s) => [s.people], (res) => res?.results],
    }),

    afterMount(({ actions, props }) => {
        if (props.url) {
            actions.loadPeople(props.url)
        }
    }),
])
