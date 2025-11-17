import posthog from 'posthog-js'
import { useEffect } from 'react'

import { IconMessage } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { formatPercentage } from 'lib/utils'
import { useMaxTool } from 'scenes/max/useMaxTool'

import { QueryBasedInsightModel } from '~/types'

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
          `${funnelContext.insightName} funnel.`
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
    })

    const handleClick = (): void => {
        posthog.capture('survey opportunity clicked', {
            linked_insight_id: insight.id,
            conversionRate: funnelContext?.conversionRate,
        })
        openMax?.()
    }

    return (
        <LemonButton size="xsmall" type="primary" sideIcon={<IconMessage />} onClick={handleClick} targetBlank>
            Ask users why
        </LemonButton>
    )
}
