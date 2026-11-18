import * as readingIsMagicPng from '@posthog/brand/hoggies/png/reading-is-magic'
import { IconBook } from '@posthog/icons'

import { pngHoggie } from 'lib/brand/hoggies'
import type { SceneProductEmptyState } from 'lib/components/ProductEmptyState/types'
import { FEATURE_FLAGS } from 'lib/constants'

import { ProductKey } from '~/queries/schema/schema-general'

import { BusinessKnowledgeSetupCard } from '../components/BusinessKnowledgeSetupCard/BusinessKnowledgeSetupCard'
import { BusinessKnowledgeTabs } from '../components/BusinessKnowledgeTabs/BusinessKnowledgeTabs'
import { BusinessKnowledgePreview } from './BusinessKnowledgePreview'
import { businessKnowledgeSetupLogic } from './businessKnowledgeSetupLogic'

const HedgehogReading = pngHoggie(readingIsMagicPng)

export const businessKnowledgeEmptyState: SceneProductEmptyState = {
    statusLogic: businessKnowledgeSetupLogic,
    // The scene already shows "not found" when the flag is off, so keep the gate behind it.
    featureFlag: FEATURE_FLAGS.PRODUCT_BUSINESS_KNOWLEDGE,
    // The gate replaces the scene, so the Libraries / Settings tab bar inside it never mounts.
    // Keep it on the frame so Settings stays reachable with no sources yet.
    SceneNav: function BusinessKnowledgeEmptyStateNav(): JSX.Element {
        return <BusinessKnowledgeTabs activeTab="sources" />
    },
    config: {
        productKey: ProductKey.BUSINESS_KNOWLEDGE,
        productName: 'Business knowledge',
        icon: <IconBook />,
        accentColor: 'var(--color-product-support-light)',
        accentColorDark: 'var(--color-product-support-dark)',
        hedgehog: HedgehogReading,
        text: {
            'needs-setup': {
                headline: 'Give the agents you build your business knowledge',
                lead: 'Add your docs, pricing, and policies once. Then connect a support agent, a help desk, or any other agent you build, and it answers from that knowledge. PostHog AI and the PostHog support agent use it too.',
            },
        },
        SetupCard: BusinessKnowledgeSetupCard,
        skippable: false,
        previewLabel: 'Example: your agents answering from your knowledge',
        Preview: BusinessKnowledgePreview,
    },
}
