import { useValues } from 'kea'
import { router } from 'kea-router'
import posthog from 'posthog-js'
import { useEffect, useState } from 'react'

import { IconMessage } from '@posthog/icons'
import { LemonButton, Tooltip } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { formatPercentage } from 'lib/utils'
import { addProductIntent, addProductIntentForCrossSell } from 'lib/utils/product-intents'
import { useMaxTool } from 'scenes/max/useMaxTool'
import { urls } from 'scenes/urls'

import { DataNodeLogicProps, dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { insightVizDataNodeKey } from '~/queries/nodes/InsightViz/InsightViz'
import {
    FunnelsQuery,
    FunnelsQueryResponse,
    InsightVizNode,
    ProductIntentContext,
    ProductKey,
    QuerySchema,
} from '~/queries/schema/schema-general'
import { InsightLogicProps } from '~/types'

import { QuickSurveyModal } from '../QuickSurveyModal'
import { SURVEY_CREATED_SOURCE } from '../constants'
import { QuickSurveyType } from '../quick-create/types'
import { captureMaxAISurveyCreationException } from '../utils'
import { SurveyableFunnelInsight, extractFunnelContext } from '../utils/opportunityDetection'

export interface SurveyOpportunityButtonProps {
    insight: SurveyableFunnelInsight
    disableAutoPromptSubmit?: boolean
    source: SURVEY_CREATED_SOURCE
    fromProduct: ProductKey
    showLabel?: boolean
    tooltip?: string
}

export function SurveyOpportunityButton({
    insight,
    disableAutoPromptSubmit,
    source,
    fromProduct,
    showLabel,
    tooltip,
}: SurveyOpportunityButtonProps): JSX.Element | null {
    const [modalOpen, setModalOpen] = useState(false)
    const { featureFlags } = useValues(featureFlagLogic)

    const shouldUseQuickCreate = featureFlags[FEATURE_FLAGS.SURVEYS_INSIGHT_BUTTON_EXPERIMENT] === 'test'

    const funnelContext = extractFunnelContext(insight)
    const initialMaxPrompt = funnelContext
        ? `${disableAutoPromptSubmit ? '' : '!'}Create a survey to help me identify and fix the root ` +
          `cause for ${formatPercentage(funnelContext.conversionRate * 100)} conversion in my ` +
          `"${funnelContext.insightName}" funnel${insight.id ? ` (\`${insight.id}\`)` : ''}. Read this insight to understand the ` +
          `conversion goal, and suggest the best display / targeting strategies.`
        : ''

    useEffect(() => {
        if (!funnelContext) {
            return
        }

        posthog.capture('survey opportunity displayed', {
            linked_insight_id: insight.id,
            conversionRate: funnelContext.conversionRate,
            source: source,
        })
    }, [insight.id, funnelContext, source])

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
                    source: source,
                    created_successfully: !toolOutput?.error,
                },
            })

            if (toolOutput?.error || !toolOutput?.survey_id) {
                return captureMaxAISurveyCreationException(toolOutput.error, source)
            }

            router.actions.push(urls.survey(toolOutput.survey_id))
        },
    })

    const handleClick = (): void => {
        posthog.capture('survey opportunity clicked', {
            linked_insight_id: insight.id,
            conversionRate: funnelContext?.conversionRate,
            source: source,
        })
        void addProductIntentForCrossSell({
            from: fromProduct,
            to: ProductKey.SURVEYS,
            intent_context: ProductIntentContext.QUICK_SURVEY_STARTED,
        })
        shouldUseQuickCreate ? setModalOpen(true) : openMax?.()
    }

    if (!funnelContext) {
        return null
    }

    const askUsersButton = (
        <LemonButton size="xsmall" type="primary" icon={<IconMessage />} onClick={handleClick}>
            {showLabel && 'Ask users why'}
        </LemonButton>
    )

    return (
        <>
            {tooltip ? <Tooltip title={tooltip}>{askUsersButton}</Tooltip> : askUsersButton}
            {shouldUseQuickCreate && (
                <QuickSurveyModal
                    context={{ type: QuickSurveyType.FUNNEL, funnel: funnelContext }}
                    isOpen={modalOpen}
                    onCancel={() => setModalOpen(false)}
                />
            )}
        </>
    )
}

export interface SurveyOpportunityButtonWithQueryProps {
    insight: {
        name: string
        query: InsightVizNode
    }
    insightProps: InsightLogicProps<QuerySchema>
    source: SURVEY_CREATED_SOURCE
    fromProduct: ProductKey
}

export function SurveyOpportunityButtonWithQuery({
    insight,
    insightProps,
    source,
    fromProduct,
}: SurveyOpportunityButtonWithQueryProps): JSX.Element | null {
    const vizKey = insightVizDataNodeKey(insightProps)
    const dataNodeLogicProps: DataNodeLogicProps = {
        key: vizKey,
        query: insight.query.source,
    }

    const { response } = useValues(dataNodeLogic(dataNodeLogicProps))

    const result = (response as FunnelsQueryResponse | null)?.results
    if (!result) {
        return null
    }

    const surveyableInsight: SurveyableFunnelInsight = {
        name: insight.name,
        query: insight.query as InsightVizNode<FunnelsQuery>,
        result,
    }

    return <SurveyOpportunityButton insight={surveyableInsight} source={source} fromProduct={fromProduct} />
}
