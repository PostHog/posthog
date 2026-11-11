import * as experimentPng from '@posthog/brand/hoggies/png/experiment'
import { IconFlask } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { pngHoggie } from 'lib/brand/hoggies'
import { ProductEmptyState } from 'lib/components/ProductEmptyState/ProductEmptyState'
import type { ProductEmptyStateConfig } from 'lib/components/ProductEmptyState/types'
import { urls } from 'scenes/urls'

import { ProductKey } from '~/queries/schema/schema-general'

import { OfflineExperimentsPreview } from '../emptyState/OfflineExperimentsPreview'

const HedgehogExperiment = pngHoggie(experimentPng)

const offlineExperimentsEmptyState: ProductEmptyStateConfig = {
    productKey: ProductKey.LLM_EVALUATIONS,
    productName: 'Offline evaluations',
    icon: <IconFlask />,
    accentColor: 'var(--color-product-llm-evaluations-light)',
    accentColorDark: 'var(--color-product-llm-analytics-dark)',
    hedgehog: HedgehogExperiment,
    text: {
        'needs-setup': {
            headline: 'Test agent changes before they reach production',
            lead: 'Compare prompt and model combinations on the same test cases. Run your agent locally or in your CI, then send results to PostHog to compare multiple scores and inspect the responses behind them.',
        },
    },
    primaryAction: {
        label: 'Run your first experiment',
        to: 'https://posthog.com/docs/ai-evals/offline-evals',
        dataAttr: 'offline-experiments-get-started',
    },
    SetupActions: function ScorerSetupAction(): JSX.Element {
        return (
            <LemonButton
                type="secondary"
                to={urls.aiObservabilityScorers()}
                className="self-start"
                data-attr="offline-experiments-set-up-scorers"
            >
                Set up scorers
            </LemonButton>
        )
    },
    docsUrl: 'https://posthog.com/docs/ai-evals/offline-evals',
    skippable: false,
    previewLabel: 'Example: compare prompts, models, and scores',
    Preview: OfflineExperimentsPreview,
}

export function OfflineExperimentsEmptyState(): JSX.Element {
    return <ProductEmptyState config={offlineExperimentsEmptyState} mode="needs-setup" />
}
