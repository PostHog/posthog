// PROTOTYPE, throwaway: where a messaging call to action sits on the feature flag page.
// Each area has its own variants, switchable via `?variant=` on the real pages.
// Lives only on the prototype branch; never merge.

import { useValues } from 'kea'
import { router } from 'kea-router'

import type { FeatureFlagType } from '~/types'

export type MessagingCtaArea = 'flags' | 'cohorts' | 'insights' | 'replay'

export type MessagingCtaVariant = 'today' | 'A' | 'B' | 'C' | 'D' | 'E' | 'F' | 'G' | 'H'

export const MESSAGING_CTA_VARIANTS_BY_AREA: Record<MessagingCtaArea, MessagingCtaVariant[]> = {
    flags: ['today', 'A', 'B', 'C'],
    cohorts: ['today', 'D', 'E'],
    insights: ['today', 'F'],
    replay: ['today', 'G', 'H'],
}

const MESSAGING_CTA_VARIANTS: MessagingCtaVariant[] = ['today', 'A', 'B', 'C', 'D', 'E', 'F', 'G', 'H']

export const MESSAGING_CTA_VARIANT_LABELS: Record<MessagingCtaVariant, string> = {
    today: 'Today',
    A: 'A (At create: form switch, automate) · channel shift: flag create',
    B: 'B (Partial rollout: rollout line, broadcast) · channel shift: rollout step',
    C: 'C (At 100%: status card, broadcast) · channel shift: roll out to everyone',
    D: 'D (Header: next to Save, broadcast)',
    E: 'E (Real-time: email people as they join, automate)',
    F: 'F (People modal: footer, broadcast)',
    G: "G (Player: next to the URL, send your app's emails)",
    H: "H (List: top row, send your app's emails)",
}

export const MESSAGING_CTA_TODAY_HINTS: Record<MessagingCtaArea, string> = {
    flags: 'The page as users see it on master.',
    cohorts: 'Master: "Email this cohort" sits in the side panel, and the toast after saving a new cohort offers it.',
    insights: 'Master: "Save as cohort" ends in a toast that offers "Email this cohort".',
    replay: 'Master: Replay has no call to action for email.',
}

export const MESSAGING_CTA_VARIANT_HINTS: Record<Exclude<MessagingCtaVariant, 'today'>, string> = {
    A: 'Open a new flag. The switch sits under Enabled.',
    B: 'Open a flag rolled out to part of its users. The action sits on the rollout line.',
    C: 'Open a flag that is on for everyone. The action sits in the status card.',
    D: 'Open a cohort without event conditions. The button sits left of Save.',
    E: 'Open a cohort with event conditions, which can be real-time. The row sits under Flag targeting.',
    F: 'Click a funnel step or a point on a trend to open its people. The button sits in the footer.',
    G: 'Open a recording. The chip sits in the player bar, after the URL.',
    H: 'The row sits at the top of the recordings list.',
}

export const PROTOTYPE_SOURCES = {
    create: 'feature_flag_create_prototype',
    partialRollout: 'feature_flag_partial_rollout_prototype',
    everyone: 'feature_flag_everyone_prototype',
    cohortHeader: 'cohort_header_prototype',
    cohortRealtime: 'cohort_realtime_prototype',
    peopleModal: 'persons_modal_prototype',
    replayPlayer: 'replay_player_prototype',
    replayList: 'replay_list_prototype',
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
