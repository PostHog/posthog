import { actions, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import {
    PulseDigestSummary,
    PulseFindingFeedbackAction,
    PulseFindingType,
    PulseSubscriptionType,
} from './pulseTypes'

const DEFAULT_SUBSCRIPTION: PulseSubscriptionType = {
    id: null,
    enabled: false,
    frequency: 'weekly',
    enabled_channels: ['in_app'],
    slack_channel_id: '',
    email_recipients: [],
    last_scan_at: null,
    next_scan_at: null,
    created_at: null,
}

export const pulseLogic = kea([
    path(['scenes', 'pulse', 'pulseLogic']),
    actions({
        loadDigests: true,
        loadFindings: true,
        loadSubscription: true,
        submitFeedback: (findingId, action) => ({ findingId, action }),
        setExpandedDigestId: (id) => ({ id }),
        updateSubscriptionLocal: (patch) => ({ patch }),
        saveSubscription: true,
    }),
    reducers({
        expandedDigestId: [
            null as string | null,
            {
                setExpandedDigestId: (_: any, { id }: { id: string | null }) => id,
            },
        ],
        subscriptionDraft: [
            null as PulseSubscriptionType | null,
            {
                loadSubscriptionSuccess: (_: any, { subscription }: { subscription: PulseSubscriptionType }) =>
                    subscription,
                updateSubscriptionLocal: (
                    state: PulseSubscriptionType | null,
                    { patch }: { patch: Partial<PulseSubscriptionType> }
                ) => (state ? { ...state, ...patch } : { ...DEFAULT_SUBSCRIPTION, ...patch }),
            },
        ],
    }),
    loaders(({ values }: any) => ({
        digests: [
            [] as PulseDigestSummary[],
            {
                loadDigests: async () => {
                    const response = await api.pulse.listDigests()
                    return response.results || []
                },
            },
        ],
        findings: [
            [] as PulseFindingType[],
            {
                loadFindings: async () => {
                    const response = await api.pulse.listFindings()
                    return response.results || []
                },
                submitFeedback: async ({
                    findingId,
                    action,
                }: {
                    findingId: string
                    action: PulseFindingFeedbackAction
                }) => {
                    const updated = await api.pulse.submitFeedback(findingId, action)
                    return values.findings.map((f: PulseFindingType) => (f.id === findingId ? updated : f))
                },
            },
        ],
        subscription: [
            null as PulseSubscriptionType | null,
            {
                loadSubscription: async () => {
                    return await api.pulse.currentSubscription()
                },
                saveSubscription: async () => {
                    const draft: PulseSubscriptionType | null = values.subscriptionDraft
                    if (!draft) {
                        return null
                    }
                    const payload = {
                        enabled: draft.enabled,
                        frequency: draft.frequency,
                        enabled_channels: draft.enabled_channels,
                        slack_channel_id: draft.slack_channel_id,
                        email_recipients: draft.email_recipients,
                    }
                    if (draft.id) {
                        return await api.pulse.updateSubscription(draft.id, payload)
                    }
                    return await api.pulse.createSubscription(payload)
                },
            },
        ],
    })),
    listeners(() => ({
        saveSubscriptionSuccess: () => {
            lemonToast.success('Pulse subscription saved')
        },
        saveSubscriptionFailure: () => {
            lemonToast.error('Failed to save Pulse subscription')
        },
        submitFeedbackSuccess: () => {
            lemonToast.success('Feedback recorded')
        },
    })),
    selectors({
        shouldShowEmptyState: [
            (s: any) => [s.digests, s.digestsLoading],
            (digests: PulseDigestSummary[], loading: boolean): boolean => !loading && digests.length === 0,
        ],
        latestDigest: [
            (s: any) => [s.digests],
            (digests: PulseDigestSummary[]): PulseDigestSummary | null => (digests.length ? digests[0] : null),
        ],
    }),
])
