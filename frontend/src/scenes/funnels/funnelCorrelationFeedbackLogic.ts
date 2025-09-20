import { actions, connect, kea, key, listeners, path, props, reducers } from 'kea'

import { lemonToast } from '@posthog/lemon-ui'

import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { keyForInsightLogicProps } from 'scenes/insights/sharedUtils'

import { InsightLogicProps } from '~/types'

import type { funnelCorrelationFeedbackLogicType } from './funnelCorrelationFeedbackLogicType'
import { funnelCorrelationLogic } from './funnelCorrelationLogic'
import { funnelPropertyCorrelationLogic } from './funnelPropertyCorrelationLogic'

export const funnelCorrelationFeedbackLogic = kea<funnelCorrelationFeedbackLogicType>([
    props({} as InsightLogicProps),
    key(keyForInsightLogicProps('insight_funnel')),
    path((key) => ['scenes', 'funnels', 'funnelCorrelationFeedbackLogic', key]),

    connect((props: InsightLogicProps) => ({
        actions: [
            funnelCorrelationLogic(props),
            ['loadEventCorrelations'],
            funnelPropertyCorrelationLogic(props),
            ['loadPropertyCorrelations'],
        ],
    })),

    actions({
        sendCorrelationAnalysisFeedback: true,
        hideCorrelationAnalysisFeedback: true,
        setCorrelationFeedbackRating: (rating: number) => ({ rating }),
        setCorrelationDetailedFeedback: (comment: string) => ({ comment }),
        setCorrelationDetailedFeedbackVisible: (visible: boolean) => ({ visible }),
    }),
    reducers({
        correlationFeedbackHidden: [
            true,
            {
                // don't load the feedback form until after some results were loaded
                loadEventCorrelations: () => false,
                loadPropertyCorrelations: () => false,
                sendCorrelationAnalysisFeedback: () => true,
                hideCorrelationAnalysisFeedback: () => true,
            },
        ],
        correlationDetailedFeedbackVisible: [
            false,
            {
                setCorrelationDetailedFeedbackVisible: (_, { visible }) => visible,
            },
        ],
        correlationFeedbackRating: [
            0,
            {
                setCorrelationFeedbackRating: (_, { rating }) => rating,
            },
        ],
        correlationDetailedFeedback: [
            '',
            {
                setCorrelationDetailedFeedback: (_, { comment }) => comment,
            },
        ],
    }),
    listeners(({ actions, values }) => ({
        sendCorrelationAnalysisFeedback: () => {
            eventUsageLogic.actions.reportCorrelationAnalysisDetailedFeedback(
                values.correlationFeedbackRating,
                values.correlationDetailedFeedback
            )
            actions.setCorrelationFeedbackRating(0)
            actions.setCorrelationDetailedFeedback('')
            lemonToast.success('Thanks for your feedback! Your comments help us improve')
        },
        setCorrelationFeedbackRating: ({ rating }) => {
            const feedbackBoxVisible = rating > 0
            actions.setCorrelationDetailedFeedbackVisible(feedbackBoxVisible)
            if (feedbackBoxVisible) {
                // Don't send event when resetting reducer
                eventUsageLogic.actions.reportCorrelationAnalysisFeedback(rating)
            }
        },
    })),
])
