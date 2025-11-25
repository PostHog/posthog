import { router } from 'kea-router'
import posthog from 'posthog-js'
import { useEffect } from 'react'

import { IconMessage } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { formatPercentage } from 'lib/utils'
import { addProductIntent } from 'lib/utils/product-intents'
import { useMaxTool } from 'scenes/max/useMaxTool'
import { urls } from 'scenes/urls'

import { ProductIntentContext, ProductKey } from '~/queries/schema/schema-general'
import { QueryBasedInsightModel } from '~/types'

import { SURVEY_CREATED_SOURCE } from '../constants'
import { captureMaxAISurveyCreationException } from '../utils'
import { extractFunnelContext } from '../utils/opportunityDetection'

export interface SurveyOpportunityButtonProps {
    insight: QueryBasedInsightModel
    disableAutoPromptSubmit?: boolean
}

export function SurveyOpportunityButton({
    insight,
    disableAutoPromptSubmit,
}: SurveyOpportunityButtonProps): JSX.Element | null {
    const funnelContext = extractFunnelContext(insight)
    const initialMaxPrompt = funnelContext
        ? `${disableAutoPromptSubmit ? '' : '!'}Create a survey to help me identify and fix the root ` +
          `cause for ${formatPercentage(funnelContext.conversionRate * 100)} conversion in my ` +
          `"${funnelContext.insightName}" funnel (\`${insight.id}\`). Read this insight to understand the ` +
          `conversion goal, and suggest the best display / targeting strategies.`
        : ''

    useEffect(() => {
        posthog.capture('survey opportunity displayed', {
            linked_insight_id: insight.id,
            conversionRate: funnelContext?.conversionRate, // oxlint-disable-line react-hooks/exhaustive-deps
        })
    }, [insight.id])

    const { openMax } = useMaxTool({
        identifier: 'create_survey',
        active: true,
        initialMaxPrompt,
        context: {
            insight_id: insight.id,
            ...funnelContext,
        },
        callback: (toolOutput: { survey_id?: string; survey_name?: string; error?: string }) => {
            addProductIntent({
                product_type: ProductKey.SURVEYS,
                intent_context: ProductIntentContext.SURVEY_CREATED,
                metadata: {
                    survey_id: toolOutput.survey_id,
                    source: SURVEY_CREATED_SOURCE.INSIGHT_CROSS_SELL,
                    created_successfully: !toolOutput?.error,
                },
            })

            if (toolOutput?.error || !toolOutput?.survey_id) {
                return captureMaxAISurveyCreationException(toolOutput.error, SURVEY_CREATED_SOURCE.INSIGHT_CROSS_SELL)
            }

            router.actions.push(urls.survey(toolOutput.survey_id))
        },
    })

    const handleClick = (): void => {
        posthog.capture('survey opportunity clicked', {
            linked_insight_id: insight.id,
            conversionRate: funnelContext?.conversionRate,
        })
        openMax?.()
    }

    return (
        <LemonButton size="xsmall" type="primary" sideIcon={<IconMessage />} onClick={handleClick}>
            Ask users why
        </LemonButton>
    )
}
