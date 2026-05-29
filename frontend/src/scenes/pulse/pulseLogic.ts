import { actions, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import type { pulseLogicType } from './pulseLogicType'
import {
    PulseDigestDetail,
    PulseDigestSummary,
    PulseFindingFeedbackAction,
    PulseFindingType,
    PulseSubscriptionType,
    PulseWatchedCandidate,
} from './pulseTypes'

const DEFAULT_SUBSCRIPTION: PulseSubscriptionType = {
    id: null,
    enabled: false,
    frequency: 'weekly',
    detection_mode: 'change_v1',
    sensitivity: 'balanced',
    min_change_pct: 0.25,
    baseline_weeks: 4,
    max_findings: 5,
    robust_z_threshold: 3.5,
    last_scan_at: null,
    next_scan_at: null,
    created_at: null,
}

export const pulseLogic = kea<pulseLogicType>([
    path(['scenes', 'pulse', 'pulseLogic']),
    actions({
        loadDigests: true,
        loadFindings: true,
        loadSubscription: true,
        loadWatched: true,
        getDigest: (id: string) => ({ id }),
        submitFeedback: (findingId: string, action: PulseFindingFeedbackAction, snoozedUntil?: string) => ({
            findingId,
            action,
            snoozedUntil,
        }),
        setExpandedDigestId: (id: string | null) => ({ id }),
        updateSubscriptionLocal: (patch: Partial<PulseSubscriptionType>) => ({ patch }),
        saveSubscription: true,
    }),
    loaders(({ values }) => ({
        digests: [
            [] as PulseDigestSummary[],
            {
                loadDigests: async () => {
                    const response = await api.pulse.listDigests()
                    return response.results || []
                },
            },
        ],
        expandedDigest: [
            null as PulseDigestDetail | null,
            {
                getDigest: async ({ id }) => await api.pulse.getDigest(id),
            },
        ],
        findings: [
            [] as PulseFindingType[],
            {
                loadFindings: async () => {
                    const response = await api.pulse.listFindings()
                    return response.results || []
                },
                submitFeedback: async ({ findingId, action, snoozedUntil }) => {
                    const updated = await api.pulse.submitFeedback(findingId, action, snoozedUntil)
                    return values.findings.map((f) => (f.id === findingId ? updated : f))
                },
            },
        ],
        subscription: [
            null as PulseSubscriptionType | null,
            {
                loadSubscription: async () => await api.pulse.currentSubscription(),
                saveSubscription: async () => {
                    const draft = values.subscriptionDraft
                    if (!draft) {
                        return null
                    }
                    const payload: Partial<PulseSubscriptionType> = {
                        enabled: draft.enabled,
                        frequency: draft.frequency,
                        detection_mode: draft.detection_mode,
                        sensitivity: draft.sensitivity,
                        min_change_pct: draft.min_change_pct,
                        baseline_weeks: draft.baseline_weeks,
                        max_findings: draft.max_findings,
                        robust_z_threshold: draft.robust_z_threshold,
                    }
                    if (draft.id) {
                        return await api.pulse.updateSubscription(draft.id, payload)
                    }
                    return await api.pulse.createSubscription(payload)
                },
            },
        ],
        watchedCandidates: [
            [] as PulseWatchedCandidate[],
            {
                loadWatched: async () => {
                    const response = await api.pulse.watchedCandidates()
                    return response.results || []
                },
            },
        ],
    })),
    reducers({
        expandedDigestId: [
            null as string | null,
            {
                setExpandedDigestId: (_, { id }) => id,
            },
        ],
        subscriptionDraft: [
            null as PulseSubscriptionType | null,
            {
                loadSubscriptionSuccess: (_, { subscription }) => subscription,
                saveSubscriptionSuccess: (_, { subscription }) => subscription,
                updateSubscriptionLocal: (state, { patch }) =>
                    state ? { ...state, ...patch } : { ...DEFAULT_SUBSCRIPTION, ...patch },
            },
        ],
        feedbackInFlight: [
            {} as Record<string, boolean>,
            {
                submitFeedback: (state, { findingId }) => ({ ...state, [findingId]: true }),
                submitFeedbackSuccess: (state, { payload }) => {
                    const next = { ...state }
                    if (payload?.findingId) {
                        delete next[payload.findingId]
                    }
                    return next
                },
                submitFeedbackFailure: (state, { errorObject }) => {
                    const next = { ...state }
                    const id = errorObject?.findingId as string | undefined
                    if (id) {
                        delete next[id]
                    }
                    return next
                },
            },
        ],
        digestsError: [
            false,
            {
                loadDigests: () => false,
                loadDigestsSuccess: () => false,
                loadDigestsFailure: () => true,
            },
        ],
        findingsError: [
            false,
            {
                loadFindings: () => false,
                loadFindingsSuccess: () => false,
                loadFindingsFailure: () => true,
            },
        ],
    }),
    listeners(() => ({
        saveSubscriptionSuccess: () => {
            lemonToast.success('Pulse settings saved')
        },
        saveSubscriptionFailure: () => {
            lemonToast.error('Failed to save Pulse settings')
        },
        submitFeedbackSuccess: () => {
            lemonToast.success('Feedback recorded')
        },
        submitFeedbackFailure: () => {
            lemonToast.error('Failed to record feedback')
        },
    })),
    selectors({
        latestDigest: [
            (s) => [s.digests],
            (digests): PulseDigestSummary | null => (digests.length ? digests[0] : null),
        ],
        shouldShowEmptyState: [
            (s) => [s.digests, s.digestsLoading],
            (digests, digestsLoading): boolean => !digestsLoading && digests.length === 0,
        ],
        findingsForLatest: [
            (s) => [s.findings, s.latestDigest],
            (findings, latestDigest): PulseFindingType[] =>
                latestDigest ? findings.filter((f) => f.digest === latestDigest.id) : [],
        ],
    }),
])
