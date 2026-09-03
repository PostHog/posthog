import * as readingIsMagicPng from '@posthog/brand/hoggies/png/reading-is-magic'
import { IconBook } from '@posthog/icons'

import { pngHoggie } from 'lib/brand/hoggies'
import type { SceneProductEmptyState } from 'lib/components/ProductEmptyState/types'
import { FEATURE_FLAGS } from 'lib/constants'

import { ProductKey } from '~/queries/schema/schema-general'

import { BusinessKnowledgePreview } from './BusinessKnowledgePreview'
import { BusinessKnowledgePrimaryAction } from './BusinessKnowledgePrimaryAction'
import { businessKnowledgeSetupLogic } from './businessKnowledgeSetupLogic'

const HedgehogReading = pngHoggie(readingIsMagicPng)

export const businessKnowledgeEmptyState: SceneProductEmptyState = {
    statusLogic: businessKnowledgeSetupLogic,
    // The scene already shows "not found" when the flag is off, so keep the gate behind it.
    featureFlag: FEATURE_FLAGS.PRODUCT_BUSINESS_KNOWLEDGE,
    config: {
        productKey: ProductKey.BUSINESS_KNOWLEDGE,
        productName: 'Business knowledge',
        icon: <IconBook />,
        accentColor: 'var(--color-product-support-light)',
        accentColorDark: 'var(--color-product-support-dark)',
        hedgehog: HedgehogReading,
        text: {
            'needs-setup': {
                headline: 'Teach PostHog AI how your business works',
                lead: 'Add pricing pages, policies, product docs, or any text, and PostHog AI uses them to answer questions with your context in mind. Sources refresh on a schedule you choose, so answers stay current as your docs change.',
            },
        },
        PrimaryAction: BusinessKnowledgePrimaryAction,
        skippable: false,
        previewLabel: 'PostHog AI, once it knows your business',
        Preview: BusinessKnowledgePreview,
    },
}
