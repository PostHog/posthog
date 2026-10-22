import { useActions } from 'kea'
import { router } from 'kea-router'
import posthog from 'posthog-js'

import { Link } from '@posthog/lemon-ui'

import { productSetupStatusLogic } from 'lib/components/ProductEmptyState/productSetupStatusLogic'
import type { ProductEmptyStateMode } from 'lib/components/ProductEmptyState/types'
import { userHasAccess } from 'lib/utils/accessControlUtils'
import { urls } from 'scenes/urls'

import { ProductKey } from '~/queries/schema/schema-general'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { TemplateCard } from './components/TemplateCard'
import { getEvaluationTemplateSelectionUrl } from './evaluationNavigation'
import { RECOMMENDED_TEMPLATE_KEYS } from './EvaluationTemplates'
import { type EvaluationTemplate, defaultEvaluationTemplates } from './templates'

const QUICK_START_TEMPLATES = RECOMMENDED_TEMPLATE_KEYS.slice(0, 4).flatMap((key) =>
    defaultEvaluationTemplates.filter((template) => template.key === key)
)

export function EvaluationQuickStart({
    mode,
    preview,
}: {
    mode: ProductEmptyStateMode
    preview: boolean
}): JSX.Element | null {
    const { reportSetupInteraction } = useActions(productSetupStatusLogic({ productKey: ProductKey.LLM_EVALUATIONS }))

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

    // Viewers see the disabled primary action instead, because every card opens the creation form.
    if (!userHasAccess(AccessControlResourceType.Evaluation, AccessControlLevel.Editor)) {
        return null
    }

    return (
        <div className="flex flex-col gap-2">
            <p className="m-0 text-sm text-secondary">Start from a template or create your own.</p>
            <div className="flex flex-col gap-2">
                {QUICK_START_TEMPLATES.map((template) => (
                    <TemplateCard key={template.key} template={template} onSelect={selectTemplate} />
                ))}
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
