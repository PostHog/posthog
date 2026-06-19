import { type ComponentType } from 'react'

import {
    BigLeaguesHog,
    BuilderHog1,
    ExplorerHog,
    ListHog,
    MicrophoneHog,
    XRayHog,
    YCHog,
} from 'lib/components/hedgehogs'

import { ProductKey } from '~/queries/schema/schema-general'

type HogComponent = ComponentType<{ className?: string }>

/** A role shown in the "What best describes you?" picker. Adds one product to the recommendation set. */
export interface OnboardingRole {
    id: string
    label: string
    /** Hedgehog portrait shown on the role card. */
    Hog: HogComponent
    color: string
    /** Extra product this role contributes to recommendations, if any. Must exist in availableOnboardingProducts. */
    addsProduct: ProductKey | null
    blurb: string
}

export const ONBOARDING_ROLES: OnboardingRole[] = [
    {
        id: 'engineer',
        label: 'Engineer',
        Hog: BuilderHog1,
        color: '#1d4aff',
        addsProduct: ProductKey.ERROR_TRACKING,
        blurb: 'Ship features, then catch and fix what breaks.',
    },
    {
        id: 'founder',
        label: 'Founder',
        Hog: YCHog,
        color: '#f54e00',
        addsProduct: ProductKey.WEB_ANALYTICS,
        blurb: 'Watch the whole business from one place.',
    },
    {
        id: 'pm',
        label: 'Product manager',
        Hog: ListHog,
        color: '#b62ad9',
        addsProduct: ProductKey.EXPERIMENTS,
        blurb: 'Funnels, experiments and what drives adoption.',
    },
    {
        id: 'marketer',
        label: 'Marketer',
        Hog: MicrophoneHog,
        color: '#6aa84f',
        addsProduct: ProductKey.WEB_ANALYTICS,
        blurb: 'Traffic, campaigns and conversion in one view.',
    },
    {
        id: 'data',
        label: 'Data / analytics',
        Hog: XRayHog,
        color: '#29abc6',
        addsProduct: ProductKey.DATA_WAREHOUSE,
        blurb: 'Model, query and warehouse all your data.',
    },
    {
        id: 'sales',
        label: 'Sales',
        Hog: BigLeaguesHog,
        color: '#e0922a',
        // The design adds a "data pipelines / CDP" product here; that is not an onboarding product, so we
        // surface the data warehouse (Stripe/Hubspot sync) as the closest revenue-signal fit.
        addsProduct: ProductKey.DATA_WAREHOUSE,
        blurb: 'Spot accounts heating up and revenue signals.',
    },
    {
        id: 'other',
        label: 'Something else',
        Hog: ExplorerHog,
        color: '#8b8f9a',
        addsProduct: null,
        blurb: "Just exploring. I'll find my way around.",
    },
]

export function findRole(id: string | null): OnboardingRole | null {
    return ONBOARDING_ROLES.find((role) => role.id === id) ?? null
}
