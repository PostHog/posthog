import { actions, connect, events, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import posthog from 'posthog-js'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { insightUsageLogic } from 'scenes/insights/insightUsageLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'
import { keyForInsightLogicProps } from 'scenes/insights/sharedUtils'

import { InsightVizNode, NodeKind } from '~/queries/schema/schema-general'
import { isFunnelsQuery, isInsightVizNode, isTrendsQuery } from '~/queries/utils'
import { InsightLogicProps } from '~/types'

import type { funnelsCueLogicType } from './funnelsCueLogicType'

export const funnelsCueLogic = kea<funnelsCueLogicType>([
    props({} as InsightLogicProps),
    key(keyForInsightLogicProps('new')),
    path((key) => ['scenes', 'insights', 'InsightTabs', 'TrendTab', 'FunnelsCue', key]),
    connect((props: InsightLogicProps) => ({
        values: [
            insightUsageLogic(props),
            ['isFirstLoad'],
            insightVizDataLogic(props),
            ['query'],
            featureFlagLogic,
            ['featureFlags'],
        ],
        actions: [insightVizDataLogic(props), ['setQuery'], featureFlagLogic, ['setFeatureFlags']],
    })),
    actions({
        optOut: (userOptedOut: boolean) => ({ userOptedOut }),
        setShouldShow: (show: boolean) => ({ show }),
        setPermanentOptOut: true,
        displayAsFunnel: true,
    }),
    reducers({
        _shouldShow: [
            false,
            {
                setShouldShow: (_, { show }) => show,
            },
        ],
        permanentOptOut: [
            false,
            {
                setPermanentOptOut: () => true,
            },
        ],
    }),
    listeners(({ actions, values }) => ({
        optOut: async ({ userOptedOut }) => {
            posthog.capture('funnel cue 7301 - terminated', { user_opted_out: userOptedOut })
            posthog.people.set({ funnels_cue_3701_opt_out: true })
            // funnels_cue_3701_opt_out -> will add the user to a FF that will permanently exclude the user
            actions.setPermanentOptOut()
        },
        setQuery: ({ query }) => {
            if (!isInsightVizNode(query)) {
                return
            }

            if (!values.isFirstLoad && isTrendsQuery(query?.source) && (query.source.series || []).length >= 3) {
                actions.setShouldShow(true)
                !values.permanentOptOut &&
                    posthog.capture('funnel cue 7301 - shown', { step_count: query.source.series.length })
            } else if (values.shown && isFunnelsQuery(query?.source)) {
                actions.optOut(false)
            } else {
                actions.setShouldShow(false)
            }
        },
        setFeatureFlags: async ({ flags }) => {
            if (flags[FEATURE_FLAGS.FUNNELS_CUE_OPT_OUT]) {
                actions.setPermanentOptOut()
            }
        },
        displayAsFunnel: () => {
            if (!isInsightVizNode(values.query) || !isTrendsQuery(values.query?.source)) {
                return
            }

            const query = JSON.parse(JSON.stringify(values.query)) as InsightVizNode
            query.source.kind = NodeKind.FunnelsQuery
            actions.setQuery(query)
        },
    })),
    selectors({
        shown: [
            (s) => [s._shouldShow, s.permanentOptOut],
            (shouldShow, permanentOptout): boolean => shouldShow && !permanentOptout,
        ],
    }),
    events(({ actions, values }) => ({
        afterMount: () => {
            if (values.featureFlags[FEATURE_FLAGS.FUNNELS_CUE_OPT_OUT]) {
                actions.setPermanentOptOut()
            }
        },
    })),
])
