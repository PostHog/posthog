// PROTOTYPE, throwaway: where a messaging call to action sits on the feature flag page.
// Round 1: three placements, one per flag moment, switchable via `?variant=` on the real flag pages.
// Lives only on the prototype branch; never merge.

import { useValues } from 'kea'
import { router } from 'kea-router'

import type { FeatureFlagType } from '~/types'

export type MessagingCtaVariant = 'today' | 'A' | 'B' | 'C'

export const MESSAGING_CTA_VARIANTS: MessagingCtaVariant[] = ['today', 'A', 'B', 'C']

export const MESSAGING_CTA_VARIANT_LABELS: Record<MessagingCtaVariant, string> = {
    today: 'Today (no call to action)',
    A: 'A (At create: form switch, automate) · channel shift: flag create',
    B: 'B (Partial rollout: rollout line, broadcast) · channel shift: rollout step',
    C: 'C (At 100%: status card, broadcast) · channel shift: roll out to everyone',
}

export const MESSAGING_CTA_VARIANT_HINTS: Record<MessagingCtaVariant, string> = {
    today: 'The page as users see it on master.',
    A: 'Open a new flag. The switch sits under Enabled.',
    B: 'Open a flag rolled out to part of its users. The action sits on the rollout line.',
    C: 'Open a flag that is on for everyone. The action sits in the status card.',
}

export const PROTOTYPE_SOURCES = {
    create: 'feature_flag_create_prototype',
    partialRollout: 'feature_flag_partial_rollout_prototype',
    everyone: 'feature_flag_everyone_prototype',
} as const

const STORAGE_KEY = 'prototype-messaging-cta-variant'

export function isMessagingCtaVariant(value: unknown): value is MessagingCtaVariant {
    return typeof value === 'string' && (MESSAGING_CTA_VARIANTS as string[]).includes(value)
}

export function currentMessagingCtaVariant(searchParams: Record<string, any>): MessagingCtaVariant {
    const fromUrl = searchParams.variant
    if (isMessagingCtaVariant(fromUrl)) {
        return fromUrl
    }
    const stored = window.sessionStorage.getItem(STORAGE_KEY)
    return isMessagingCtaVariant(stored) ? stored : 'today'
}

export function setMessagingCtaVariant(variant: MessagingCtaVariant): void {
    window.sessionStorage.setItem(STORAGE_KEY, variant)
    router.actions.replace(
        router.values.location.pathname,
        { ...router.values.searchParams, variant },
        router.values.hashParams
    )
}

export function rememberVariantFromUrl(searchParams: Record<string, any>): void {
    if (isMessagingCtaVariant(searchParams.variant)) {
        window.sessionStorage.setItem(STORAGE_KEY, searchParams.variant)
    }
}

// Variant A: the create form's switch is read at save time, after the form state is gone.
export const createFormPrototypeState = { emailOnFirstExposure: false }

export function rolloutPercentages(flag: Pick<FeatureFlagType, 'filters'>): number[] {
    return (flag.filters?.groups ?? []).map((group) => group.rollout_percentage ?? 100)
}

export function isPartialRollout(flag: Pick<FeatureFlagType, 'active' | 'filters'>): boolean {
    return flag.active && rolloutPercentages(flag).some((rollout) => rollout > 0 && rollout < 100)
}

export function useMessagingCtaVariant(): MessagingCtaVariant {
    const { searchParams } = useValues(router)
    return currentMessagingCtaVariant(searchParams)
}
