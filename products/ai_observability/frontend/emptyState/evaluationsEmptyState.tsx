import * as judgePng from '@posthog/brand/hoggies/png/judge'
import { IconListCheck } from '@posthog/icons'

import { pngHoggie } from 'lib/brand/hoggies'
import type { SceneProductEmptyState } from 'lib/components/ProductEmptyState/types'

import { ProductKey } from '~/queries/schema/schema-general'

import { EvaluationQuickStart } from '../evaluations/EvaluationQuickStart'
import { EvaluationsTabs } from '../evaluations/EvaluationsTabs'
import { EvaluationsPreview } from './EvaluationsPreview'
import { evaluationsSetupLogic } from './evaluationsSetupLogic'

const HedgehogJudge = pngHoggie(judgePng)

export const evaluationsEmptyState: SceneProductEmptyState = {
    statusLogic: evaluationsSetupLogic,
    SceneNav: function EvaluationsEmptyStateNav(): JSX.Element {
        return <EvaluationsTabs activeTab="online-evals" />
    },
    config: {
        productKey: ProductKey.LLM_EVALUATIONS,
        productName: 'Online evaluations',
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
        // Owns the primary-action slot so the shared fallback button doesn't come back; the quick start below is the only CTA.
        PrimaryAction: () => null,
        SetupActions: EvaluationQuickStart,
        docsUrl: 'https://posthog.com/docs/ai-evals/evaluations',
        skippable: false,
        previewLabel: 'Example: how your evaluations will score',
        Preview: EvaluationsPreview,
    },
}
