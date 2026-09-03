import * as judgePng from '@posthog/brand/hoggies/png/judge'
import { IconListCheck } from '@posthog/icons'

import { pngHoggie } from 'lib/brand/hoggies'
import type { SceneProductEmptyState } from 'lib/components/ProductEmptyState/types'
import { urls } from 'scenes/urls'

import { ProductKey } from '~/queries/schema/schema-general'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { EvaluationsPreview } from './EvaluationsPreview'
import { evaluationsSetupLogic } from './evaluationsSetupLogic'

const HedgehogJudge = pngHoggie(judgePng)

export const evaluationsEmptyState: SceneProductEmptyState = {
    statusLogic: evaluationsSetupLogic,
    config: {
        productKey: ProductKey.LLM_EVALUATIONS,
        productName: 'Evaluations',
        icon: <IconListCheck />,
        accentColor: 'var(--color-product-llm-evaluations-light)',
        accentColorDark: 'var(--color-product-llm-analytics-dark)',
        hedgehog: HedgehogJudge,
        text: {
            'needs-setup': {
                headline: 'Score AI responses as they happen',
                lead: 'Score your generations, traces, or sessions in production. Use an LLM as a judge, Hog code, or sentiment analysis for a wide range of checks. Start with a template, from scratch, or with PostHog AI, then view pass rates over time and jump straight into the runs that failed.',
            },
        },
        primaryAction: {
            label: 'Create your first evaluation',
            to: urls.aiObservabilityEvaluationTemplates(),
            accessControl: {
                resourceType: AccessControlResourceType.Evaluation,
                minAccessLevel: AccessControlLevel.Editor,
            },
            dataAttr: 'create-evaluation-button',
        },
        docsUrl: 'https://posthog.com/docs/ai-evals/evaluations',
        skippable: false,
        previewLabel: 'Your evaluations, once running',
        Preview: EvaluationsPreview,
    },
}
