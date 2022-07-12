import { kea } from 'kea'
import { InsightLogicProps, InsightType } from '~/types'
import { keyForInsightLogicProps } from 'scenes/insights/sharedUtils'
import { insightLogic } from 'scenes/insights/insightLogic'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import posthog from 'posthog-js'
import { FEATURE_FLAGS } from 'lib/constants'
import type { funnelsCueLogicType } from './funnelsCueLogicType'

export const funnelsCueLogic = kea<funnelsCueLogicType>({
    props: {} as InsightLogicProps,
    key: keyForInsightLogicProps('new'),
    path: (key) => ['scenes', 'insights', 'InsightTabs', 'TrendTab', 'FunnelsCue', key],
    connect: (props: InsightLogicProps) => ({
        values: [insightLogic(props), ['filters', 'isFirstLoad'], featureFlagLogic, ['featureFlags']],
        actions: [insightLogic(props), ['setFilters'], featureFlagLogic, ['setFeatureFlags']],
    }),
    actions: {
        optOut: (userOptedOut: boolean) => ({ userOptedOut }),
        setShouldShow: (show: boolean) => ({ show }),
        setPermanentOptOut: true,
    },
    reducers: {
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
    },
    listeners: ({ actions, values }) => ({
        optOut: async ({ userOptedOut }) => {
            posthog.capture('funnel cue 7301 - terminated', { user_opted_out: userOptedOut })
            posthog.people.set({ funnels_cue_3701_opt_out: true })
            // funnels_cue_3701_opt_out -> will add the user to a FF that will permanently exclude the user
            actions.setPermanentOptOut()
        },
        setFilters: async ({ filters }) => {
            const step_count = (filters.events?.length ?? 0) + (filters.actions?.length ?? 0)
            if (!values.isFirstLoad && filters.insight === InsightType.TRENDS && step_count >= 3) {
                actions.setShouldShow(true)
                !values.permanentOptOut && posthog.capture('funnel cue 7301 - shown', { step_count })
            } else if (values.shown && filters.insight === InsightType.FUNNELS) {
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
    }),
    selectors: {
        shown: [
            (s) => [s._shouldShow, s.permanentOptOut],
            (shouldShow, permanentOptout): boolean => shouldShow && !permanentOptout,
        ],
    },
    events: ({ actions, values }) => ({
        afterMount: async () => {
            if (values.featureFlags[FEATURE_FLAGS.FUNNELS_CUE_OPT_OUT]) {
                actions.setPermanentOptOut()
            }
        },
    }),
})
