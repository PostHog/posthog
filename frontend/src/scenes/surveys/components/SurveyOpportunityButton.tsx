import posthog from 'posthog-js'

import { IconMessage } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { useMaxTool } from 'scenes/max/useMaxTool'

import { QueryBasedInsightModel } from '~/types'

import { extractFunnelContext } from '../utils/opportunityDetection'

export interface SurveyOpportunityButtonProps {
    insight: QueryBasedInsightModel
}

export function SurveyOpportunityButton({ insight }: SurveyOpportunityButtonProps): JSX.Element | null {
    const funnelContext = extractFunnelContext(insight)
    const initialMaxPrompt = funnelContext
        ? `!Create a survey to help me identify and fix the root cause for ${Math.round(funnelContext.conversionRate)}% conversion in my ${funnelContext.insightName} funnel.`
        : ''

    const { openMax } = useMaxTool({
        identifier: 'create_survey',
        active: true,
        initialMaxPrompt,
        context: {
            insight_id: insight.id,
            ...funnelContext,
        },
    })

    const handleClick = (): void => {
        posthog.capture('survey opportunity clicked', {
            insight: insight.id,
        })
        openMax?.()
    }

    return (
        <LemonButton size="xsmall" type="primary" sideIcon={<IconMessage />} onClick={handleClick} targetBlank>
            Ask users why
        </LemonButton>
    )
}
