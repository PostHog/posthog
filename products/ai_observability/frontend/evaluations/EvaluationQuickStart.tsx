import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import posthog from 'posthog-js'

import { Link } from '@posthog/lemon-ui'

import { productSetupStatusLogic } from 'lib/components/ProductEmptyState/productSetupStatusLogic'
import type { ProductEmptyStateMode } from 'lib/components/ProductEmptyState/types'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { userHasAccess } from 'lib/utils/accessControlUtils'
import { urls } from 'scenes/urls'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { AgentMode } from '~/queries/schema/schema-assistant-messages'
import { ProductKey } from '~/queries/schema/schema-general'
import { AccessControlLevel, AccessControlResourceType, SidePanelTab } from '~/types'

import { llmProviderKeysLogic } from '../settings/llmProviderKeysLogic'
import { ScratchTemplateCard } from './components/ScratchTemplateCard'
import { SuggestEvalsCard } from './components/SuggestEvalsCard'
import { TemplateCard } from './components/TemplateCard'
import { getEvaluationTemplateSelectionUrl } from './evaluationNavigation'
import { recommendedTemplates } from './EvaluationTemplates'
import type { EvaluationTemplate } from './templates'

const SUGGEST_EVALS_PROMPT =
    "Look at this project's recent AI traces. Find and rank the real failure modes, with an example trace for each and how often it appears. Recommend one evaluation per failure mode, and say whether it should return pass/fail, a score, or categories. Prefer Hog code checks and sentiment, which need no provider API key. Ask which ones I want before creating anything. Test the Hog checks I pick on recent data, then create the evaluations I pick as disabled and give me links to review and enable them."

export function EvaluationQuickStart({
    mode,
    preview,
}: {
    mode: ProductEmptyStateMode
    preview: boolean
}): JSX.Element | null {
    const { reportSetupInteraction } = useActions(productSetupStatusLogic({ productKey: ProductKey.LLM_EVALUATIONS }))
    const { requiresProviderKey } = useValues(llmProviderKeysLogic)
    const { openSidePanel } = useActions(sidePanelStateLogic)
    const suggestEvalsEnabled = useFeatureFlag('LLM_ANALYTICS_SUGGEST_EVALS')
    const quickStartTemplates = recommendedTemplates(requiresProviderKey).slice(0, 3)

    const selectTemplate = (template: EvaluationTemplate, placement: 'card' | 'example'): void => {
        // pinned: same analytics event as the template picker, so template funnels count both entry points
        posthog.capture('llm evaluation template selected', {
            template_key: template.key,
            output_type: template.output_type,
            placement,
            source: 'empty_state_quick_start',
        })
        reportSetupInteraction('template selected', mode, null, preview)
        router.actions.push(getEvaluationTemplateSelectionUrl(router.values.searchParams, template.key))
    }

    const startFromScratch = (): void => {
        posthog.capture('llm evaluation template selected', {
            template_key: 'blank',
            placement: 'card',
            source: 'empty_state_quick_start',
        })
        reportSetupInteraction('template selected', mode, null, preview)
        router.actions.push(getEvaluationTemplateSelectionUrl(router.values.searchParams))
    }

    const suggestEvals = (): void => {
        // pinned: analytics event name, the suggested-evals funnel starts here
        posthog.capture('llm evaluation suggest clicked', { source: 'empty_state_quick_start' })
        reportSetupInteraction('suggest evals clicked', mode, null, preview)
        openSidePanel(SidePanelTab.Max, `mode=${AgentMode.AIObservability}:!${SUGGEST_EVALS_PROMPT}`)
    }

    // Every card opens the creation form, so a viewer sees no quick start at all.
    if (!userHasAccess(AccessControlResourceType.Evaluation, AccessControlLevel.Editor)) {
        return null
    }

    return (
        <div className="flex flex-col gap-2">
            <div className="grid gap-2">
                {suggestEvalsEnabled && <SuggestEvalsCard onSelect={suggestEvals} />}
                {quickStartTemplates.map((template) => (
                    <TemplateCard key={template.key} template={template} onSelect={selectTemplate} />
                ))}
                <ScratchTemplateCard onSelect={startFromScratch} />
            </div>
            <Link
                to={urls.aiObservabilityEvaluationTemplates()}
                className="self-start text-sm"
                data-attr="evaluation-quick-start-more-templates"
                onClick={() => reportSetupInteraction('more templates clicked', mode, null, preview)}
            >
                Or choose from more templates
            </Link>
        </div>
    )
}
