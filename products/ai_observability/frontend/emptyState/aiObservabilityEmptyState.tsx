import * as magnifyingGlassPng from '@posthog/brand/hoggies/png/magnifying-glass-1'
import { IconLlmAnalytics } from '@posthog/icons'

import { pngHoggie } from 'lib/brand/hoggies'
import type { SceneProductEmptyState } from 'lib/components/ProductEmptyState/types'

import { ProductKey } from '~/queries/schema/schema-general'

import { aiObservabilitySharedLogic } from '../aiObservabilitySharedLogic'
import { AIObservabilityTracePreview } from './AIObservabilityTracePreview'

const HedgehogMagnifyingGlass = pngHoggie(magnifyingGlassPng)

export const aiObservabilityEmptyState: SceneProductEmptyState = {
    statusLogic: aiObservabilitySharedLogic,
    config: {
        productKey: ProductKey.AI_OBSERVABILITY,
        productName: 'AI observability',
        icon: <IconLlmAnalytics />,
        accentColor: 'var(--color-product-llm-analytics-light)',
        accentColorDark: 'var(--color-product-llm-analytics-dark)',
        hedgehog: HedgehogMagnifyingGlass,
        text: {
            'needs-setup': {
                headline: 'Know what your LLM calls cost and why they fail',
                lead: 'Capture every generation your app makes: the full conversation, model, latency, and cost, tied to the users and sessions behind it.',
                hint: 'Point Wizard at your project. The setup agent instruments your LLM calls for you:',
            },
        },
        wizard: { slug: 'ai-observability', pinProjectId: true },
        docsUrl: 'https://posthog.com/docs/ai-observability',
        manualSetupUrl: 'https://posthog.com/docs/ai-observability/installation',
        previewLabel: 'Generations, once connected',
        Preview: AIObservabilityTracePreview,
    },
}
