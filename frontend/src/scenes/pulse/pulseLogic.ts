import { actions, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import type { pulseLogicType } from './pulseLogicType'
import {
    PulseDigestDetail,
    PulseDigestSummary,
    PulseFindingType,
    PulseSubscriptionType,
    PulseWatchedCandidate,
} from './pulseTypes'

const SCAN_POLL_INTERVAL_MS = 3000
const SCAN_POLL_ATTEMPTS = 40 // ~2 minutes — covers a slow scan plus digest synthesis

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
        setExpandedDigestId: (id: string | null) => ({ id }),
        updateSubscriptionLocal: (patch: Partial<PulseSubscriptionType>) => ({ patch }),
        saveSubscription: true,
        pollScan: true,
        markScanInProgress: true,
        scanResolved: true,
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
        scanTrigger: [
            null as { workflow_id: string } | null,
            {
                triggerScan: async () => await api.pulse.triggerScan(),
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
        isScanInProgress: [
            false,
            {
                triggerScanSuccess: () => true,
                triggerScanFailure: () => false,
                markScanInProgress: () => true,
                scanResolved: () => false,
            },
        ],
    }),
    listeners(({ actions, values, cache }) => ({
        saveSubscriptionSuccess: () => {
            lemonToast.success('Pulse settings saved')
        },
        saveSubscriptionFailure: () => {
            lemonToast.error('Failed to save Pulse settings')
        },
        triggerScan: () => {
            // Remember the current digest so we can tell when a *new* one finishes (the scan creates a
            // fresh digest), and budget a bounded number of polls so we don't loop forever.
            cache.preScanDigestId = values.latestDigest?.id ?? null
            cache.scanPollsLeft = SCAN_POLL_ATTEMPTS
        },
        triggerScanSuccess: () => {
            lemonToast.success('Pulse scan started — findings will appear here shortly.')
            actions.pollScan()
        },
        triggerScanFailure: () => {
            lemonToast.error('Failed to start Pulse scan.')
        },
        pollScan: async (_, breakpoint) => {
            await breakpoint(SCAN_POLL_INTERVAL_MS)
            actions.loadDigests()
            actions.loadFindings()
        },
        loadDigestsSuccess: ({ digests }) => {
            const latest = digests[0]
            const isGenerating = !!latest && (latest.status === 'pending' || latest.status === 'generating')
            if (values.isScanInProgress) {
                cache.scanPollsLeft = (cache.scanPollsLeft ?? 0) - 1
                // Done once a *new* digest (different from the one present at trigger time) has settled,
                // i.e. findings AND the summary are ready — or once the poll budget runs out.
                const newDigestSettled =
                    !!latest &&
                    latest.id !== cache.preScanDigestId &&
                    (latest.status === 'delivered' || latest.status === 'failed')
                if (newDigestSettled || cache.scanPollsLeft <= 0) {
                    actions.scanResolved()
                } else {
                    actions.pollScan()
                }
            } else if (isGenerating) {
                // A scan we didn't trigger here (e.g. scheduled) is mid-flight — reflect it and poll.
                cache.preScanDigestId = null
                cache.scanPollsLeft = SCAN_POLL_ATTEMPTS
                actions.markScanInProgress()
                actions.pollScan()
            }
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
