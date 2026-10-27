import { useActions } from 'kea'

import * as organizedPng from '@posthog/brand/hoggies/png/organized'
import { IconBook, IconListCheck } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { pngHoggie } from 'lib/brand/hoggies'
import { ProductEmptyState } from 'lib/components/ProductEmptyState/ProductEmptyState'
import type { ProductEmptyStateConfig } from 'lib/components/ProductEmptyState/types'
import { urls } from 'scenes/urls'

import { ProductKey } from '~/queries/schema/schema-general'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { ScorersPreview } from '../emptyState/ScorersPreview'
import { aiObservabilityScoreDefinitionsLogic } from './aiObservabilityScoreDefinitionsLogic'

const HedgehogOrganized = pngHoggie(organizedPng)

const scorersEmptyState: ProductEmptyStateConfig = {
    productKey: ProductKey.LLM_EVALUATIONS,
    productName: 'Scorers',
    icon: <IconListCheck />,
    accentColor: 'var(--color-product-llm-evaluations-light)',
    accentColorDark: 'var(--color-product-llm-analytics-dark)',
    hedgehog: HedgehogOrganized,
    text: {
        'needs-setup': {
            headline: 'Define how you measure agent quality',
            lead: 'Create numeric, boolean, or categorical scorers once. Use them to record results from offline evaluations and to score production traces during manual reviews, so both workflows use the same criteria.',
        },
    },
    primaryAction: {
        label: 'Create your first scorer',
        to: urls.aiObservabilityScorer('new'),
        dataAttr: 'llma-scorers-create-button',
        accessControl: {
            resourceType: AccessControlResourceType.LlmAnalytics,
            minAccessLevel: AccessControlLevel.Editor,
        },
    },
    SetupActions: function ScorerSetupLinks(): JSX.Element {
        const { setFilters } = useActions(aiObservabilityScoreDefinitionsLogic())
        return (
            <div className="flex flex-wrap gap-2">
                <LemonButton
                    type="tertiary"
                    icon={<IconBook />}
                    to="https://posthog.com/docs/ai-evals/offline-evals"
                    targetBlank
                    data-attr="llma-scorers-offline-docs"
                >
                    Offline evaluation docs
                </LemonButton>
                <LemonButton
                    type="tertiary"
                    icon={<IconBook />}
                    to="https://posthog.com/docs/ai-observability/trace-reviews"
                    targetBlank
                    data-attr="llma-scorers-review-docs"
                >
                    Manual review docs
                </LemonButton>
                <LemonButton
                    type="tertiary"
                    onClick={() => setFilters({ archived: 'true' }, true, false)}
                    data-attr="llma-scorers-view-archived"
                >
                    View archived scorers
                </LemonButton>
            </div>
        )
    },
    skippable: false,
    previewLabel: 'Example: shared scorers for experiments and reviews',
    Preview: ScorersPreview,
}

export function ScorersEmptyState(): JSX.Element {
    return <ProductEmptyState config={scorersEmptyState} mode="needs-setup" />
}
