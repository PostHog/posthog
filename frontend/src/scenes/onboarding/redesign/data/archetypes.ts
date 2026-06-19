import { type ComponentType } from 'react'

import { IconAI, IconBuilding, IconCart, IconPhone, IconShuffle, IconTerminal } from '@posthog/icons'

import { ProductKey } from '~/queries/schema/schema-general'

type IconComponent = ComponentType<{ className?: string; color?: string }>

/** A company archetype shown on the "What are you building?" step. Drives product recommendations. */
export interface CompanyArchetype {
    id: string
    label: string
    description: string
    Icon: IconComponent
    /** Accent hue for the card — literal brand-palette value, matching the productRecommendations.ts convention. */
    color: string
    /** Products recommended for this archetype, highest priority first. All must exist in availableOnboardingProducts. */
    recommendedProducts: ProductKey[]
}

export const COMPANY_ARCHETYPES: CompanyArchetype[] = [
    {
        id: 'b2b_saas',
        label: 'B2B SaaS',
        description: 'Software sold to other businesses',
        Icon: IconBuilding,
        color: '#1d4aff',
        recommendedProducts: [ProductKey.PRODUCT_ANALYTICS, ProductKey.SESSION_REPLAY, ProductKey.FEATURE_FLAGS],
    },
    {
        id: 'consumer',
        label: 'Consumer app',
        description: 'High volume mobile or web app',
        Icon: IconPhone,
        color: '#f35454',
        recommendedProducts: [ProductKey.PRODUCT_ANALYTICS, ProductKey.SESSION_REPLAY, ProductKey.SURVEYS],
    },
    {
        id: 'ecommerce',
        label: 'Ecommerce',
        description: 'Storefront, cart and checkout',
        Icon: IconCart,
        color: '#6aa84f',
        recommendedProducts: [ProductKey.WEB_ANALYTICS, ProductKey.PRODUCT_ANALYTICS, ProductKey.SURVEYS],
    },
    {
        id: 'ai_product',
        label: 'AI product',
        description: 'LLM powered features and agents',
        Icon: IconAI,
        color: '#8567ff',
        recommendedProducts: [ProductKey.AI_OBSERVABILITY, ProductKey.PRODUCT_ANALYTICS, ProductKey.FEATURE_FLAGS],
    },
    {
        id: 'marketplace',
        label: 'Marketplace',
        description: 'Two sided supply and demand',
        Icon: IconShuffle,
        color: '#b62ad9',
        recommendedProducts: [ProductKey.PRODUCT_ANALYTICS, ProductKey.EXPERIMENTS, ProductKey.WEB_ANALYTICS],
    },
    {
        id: 'dev_tool',
        label: 'Developer tool',
        description: 'APIs, SDKs and CLIs',
        Icon: IconTerminal,
        color: '#eb9d2a',
        recommendedProducts: [ProductKey.PRODUCT_ANALYTICS, ProductKey.ERROR_TRACKING, ProductKey.FEATURE_FLAGS],
    },
]

export function findArchetype(id: string | null): CompanyArchetype | null {
    return COMPANY_ARCHETYPES.find((archetype) => archetype.id === id) ?? null
}
