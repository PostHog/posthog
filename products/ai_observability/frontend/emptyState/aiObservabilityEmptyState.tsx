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
                headline: 'See how people use your AI product and where it breaks',
                lead: 'Capture every generation with its full conversation, tied to the user and session behind it, so you can watch real usage and debug what went wrong.',
                hint: 'Point Wizard at your project. The setup agent instruments your LLM calls for you:',
            },
        },
        wizard: { slug: 'ai-observability', pinProjectId: true },
        docsUrl: 'https://posthog.com/docs/ai-observability',
        manualSetupUrl: 'https://posthog.com/docs/ai-observability/installation',
        previewLabel: 'Sessions, once connected',
        Preview: AIObservabilityTracePreview,
    },
}
