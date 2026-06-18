import { RRule } from 'rrule'

import { IconLetter } from '@posthog/icons'
import { LemonSelectOption, LemonSelectOptionLeaf, LemonSelectOptions } from '@posthog/lemon-ui'

import { IconSlack } from 'lib/lemon-ui/icons'
import { range } from 'lib/utils/arrays'
import { urls } from 'scenes/urls'

import { SubscriptionAIPromptMaxLength } from '~/queries/schema/schema-general'
import { InsightShortId, SubscriptionType } from '~/types'

export const AI_PROMPT_MAX_LENGTH = SubscriptionAIPromptMaxLength.CHARACTERS

export interface SubscriptionBaseProps {
    dashboardId?: number
    insightShortId?: InsightShortId
}

export const urlForSubscriptions = ({ dashboardId, insightShortId }: SubscriptionBaseProps): string => {
    if (insightShortId) {
        return urls.insightSubcriptions(insightShortId)
    } else if (dashboardId) {
        return urls.dashboardSubscriptions(dashboardId)
    }
    // Parent-less (e.g. AI prompt) subscriptions live at the top-level list.
    return urls.subscriptions()
}

export const urlForSubscription = (
    id: number | 'new',
    { dashboardId, insightShortId }: SubscriptionBaseProps
): string => {
    if (insightShortId) {
        return urls.insightSubcription(insightShortId, id.toString())
    } else if (dashboardId) {
        return urls.dashboardSubscription(dashboardId, id.toString())
    }
    // Parent-less (e.g. AI prompt) subscriptions: top-level detail/new page.
    return id === 'new' ? urls.subscriptionNew() : urls.subscription(id)
}

export const targetTypeOptions: LemonSelectOptions<'email' | 'slack'> = [
    { value: 'email', label: 'Email', icon: <IconLetter /> },
    { value: 'slack', label: 'Slack', icon: <IconSlack /> },
]

export const intervalOptions: LemonSelectOptions<number> = range(1, 13).map((x) => ({ value: x, label: x.toString() }))

export type FrequencyOptionValue = 'daily' | 'weekly' | 'monthly'

export const frequencyOptionsSingular: LemonSelectOption<FrequencyOptionValue>[] = [
    { value: 'daily', label: 'day' },
    { value: 'weekly', label: 'week' },
    { value: 'monthly', label: 'month' },
]
export const frequencyOptionsPlural: LemonSelectOption<FrequencyOptionValue>[] = [
    { value: 'daily', label: 'days' },
    { value: 'weekly', label: 'weeks' },
    { value: 'monthly', label: 'months' },
]

export const weekdayOptions: LemonSelectOptionLeaf<
    'monday' | 'tuesday' | 'wednesday' | 'thursday' | 'friday' | 'saturday' | 'sunday'
>[] = [
    { value: 'monday', label: 'Monday' },
    { value: 'tuesday', label: 'Tuesday' },
    { value: 'wednesday', label: 'Wednesday' },
    { value: 'thursday', label: 'Thursday' },
    { value: 'friday', label: 'Friday' },
    { value: 'saturday', label: 'Saturday' },
    { value: 'sunday', label: 'Sunday' },
]

export const WEEKDAYS: Set<string> = new Set(['monday', 'tuesday', 'wednesday', 'thursday', 'friday'])

export const monthlyWeekdayOptions: LemonSelectOptions<
    'monday' | 'tuesday' | 'wednesday' | 'thursday' | 'friday' | 'saturday' | 'sunday' | 'day' | 'weekday'
> = [...weekdayOptions, { value: 'day', label: 'day' }, { value: 'weekday', label: 'weekday' }]

export const bysetposOptions: LemonSelectOptions<'1' | '2' | '3' | '4' | '-1'> = [
    { value: '1', label: 'first' },
    { value: '2', label: 'second' },
    { value: '3', label: 'third' },
    { value: '4', label: 'fourth' },
    { value: '-1', label: 'last' },
]

export const timeOptions: LemonSelectOptions<string> = range(0, 24).map((x) => ({
    value: String(x),
    label: `${String(x).padStart(2, '0')}:00`,
}))

const RRULE_WEEKDAY_MAP: Record<string, (typeof RRule)['MO']> = {
    monday: RRule.MO,
    tuesday: RRule.TU,
    wednesday: RRule.WE,
    thursday: RRule.TH,
    friday: RRule.FR,
    saturday: RRule.SA,
    sunday: RRule.SU,
}

const RRULE_FREQ_MAP: Record<string, number> = {
    daily: RRule.DAILY,
    weekly: RRule.WEEKLY,
    monthly: RRule.MONTHLY,
    yearly: RRule.YEARLY,
}

// Client-side preview only — the authoritative next delivery date is computed
// server-side in posthog/models/subscription.py (Subscription.set_next_delivery_date)
export function getNextDeliveryDate(subscription: Partial<SubscriptionType>): Date | null {
    if (!subscription.frequency || !subscription.start_date) {
        return null
    }
    try {
        const rule = new RRule({
            freq: RRULE_FREQ_MAP[subscription.frequency],
            interval: subscription.interval ?? 1,
            dtstart: new Date(subscription.start_date),
            byweekday: subscription.byweekday?.map((d) => RRULE_WEEKDAY_MAP[d]) ?? null,
            bysetpos: subscription.bysetpos ?? null,
        })
        return rule.after(new Date())
    } catch {
        return null
    }
}

export interface AiSubscriptionGateInputs {
    isAiPrompt: boolean
    isParentless: boolean
    isEditing: boolean
    aiConsentApproved: boolean
    isCloud: boolean
    isDebug: boolean
    aiFlagEnabled: boolean
}

export interface AiSubscriptionGate {
    /** Org cleared every gate (consent + cloud/debug + flag) needed to author an AI report. */
    aiAllowed: boolean
    /** Show the "What to send" (insight vs AI) toggle — new parent-anchored subs, feature on. */
    showResourceTypeToggle: boolean
    /** The AI option in the toggle is selectable (vs greyed with a consent reason). */
    aiOptionEnabled: boolean
    /** Insight-flow hint: feature exists but consent is missing. */
    showConsentHint: boolean
    /** AI-only-form banner: feature exists, consent missing, creating (not editing). */
    showAiFormConsentBanner: boolean
    /** Block submit on a new AI subscription that can't be created — mirrors the create-only backend gate. */
    submitBlocked: boolean
}

/**
 * Single source of truth for how the AI-subscription feature flag (visibility) and the
 * org AI-data-processing consent (enablement) gate the subscription form. Pure so the
 * flag-off / consent-missing combinations are provable without rendering the component.
 *
 * - flag off → the feature does not exist: hide the toggle, option, and banners.
 * - flag on, no consent → it exists but is blocked: toggle shows with AI greyed + a consent
 *   hint; submit is blocked on the AI-only form.
 * - editing → never block (the backend gates creation only; users must be able to edit/disable).
 */
export function getAiSubscriptionGate(inputs: AiSubscriptionGateInputs): AiSubscriptionGate {
    const { isAiPrompt, isParentless, isEditing, aiConsentApproved, isCloud, isDebug, aiFlagEnabled } = inputs
    const aiAllowed = aiConsentApproved && (isCloud || isDebug) && aiFlagEnabled
    const showResourceTypeToggle = !isParentless && !isEditing && aiFlagEnabled
    return {
        aiAllowed,
        showResourceTypeToggle,
        aiOptionEnabled: aiAllowed,
        showConsentHint: showResourceTypeToggle && !aiAllowed,
        showAiFormConsentBanner: isAiPrompt && !isEditing && aiFlagEnabled && !aiAllowed,
        submitBlocked: isAiPrompt && !isEditing && !aiAllowed,
    }
}
