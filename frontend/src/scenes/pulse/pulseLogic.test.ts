import { MOCK_DEFAULT_USER } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { userLogic } from 'scenes/userLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { pulseLogic } from './pulseLogic'

const DIGEST = {
    id: 'd1',
    period_start: '2026-05-19',
    period_end: '2026-05-26',
    status: 'delivered',
    created_at: '2026-05-26T00:00:00Z',
    finding_count: 1,
}

const FINDING = {
    id: 'f1',
    digest: 'd1',
    metric_label: 'Pageviews',
    metric_descriptor: {},
    current_value: 100,
    baseline_value: 50,
    change_pct: 1.0,
    robust_z: 4.2,
    impact: 7.07,
    attribution_breakdown: null,
    narrative: 'Pageviews doubled.',
    chart_thumbnail_url: '',
    rank: 0,
    created_at: '2026-05-26T00:00:00Z',
}

const SUBSCRIPTION = {
    id: 's1',
    enabled: true,
    frequency: 'weekly',
    detection_mode: 'change_v1',
    sensitivity: 'balanced',
    min_change_pct: 0.25,
    baseline_weeks: 4,
    max_findings: 5,
    robust_z_threshold: 3.5,
    last_scan_at: null,
    next_scan_at: null,
    created_at: '2026-05-26T00:00:00Z',
}

const WATCHED = { source: 'recent_insight', source_id: '7', label: 'Signups', query: { kind: 'TrendsQuery' } }

describe('pulseLogic', () => {
    let logic: ReturnType<typeof pulseLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                '/api/environments/:team_id/pulse_digests/': () => [200, { count: 1, results: [DIGEST] }],
                '/api/environments/:team_id/pulse_digests/d1/': () => [200, { ...DIGEST, findings: [FINDING] }],
                '/api/environments/:team_id/pulse_findings/': () => [200, { count: 1, results: [FINDING] }],
                '/api/environments/:team_id/pulse_subscriptions/current/': () => [200, SUBSCRIPTION],
                '/api/environments/:team_id/pulse_subscriptions/watched/': () => [200, { results: [WATCHED] }],
            },
            patch: {
                '/api/environments/:team_id/pulse_subscriptions/:id/': () => [
                    200,
                    { ...SUBSCRIPTION, sensitivity: 'sensitive' },
                ],
            },
        })
        initKeaTests()
        userLogic.mount()
        userLogic.actions.loadUserSuccess(MOCK_DEFAULT_USER)
        logic = pulseLogic()
        logic.mount()
    })

    it('loads digests, findings and subscription into typed values', async () => {
        await expectLogic(logic, () => {
            logic.actions.loadDigests()
            logic.actions.loadFindings()
            logic.actions.loadSubscription()
        })
            .toDispatchActions(['loadDigestsSuccess', 'loadFindingsSuccess', 'loadSubscriptionSuccess'])
            .toMatchValues({
                digests: [DIGEST],
                findings: [FINDING],
                subscription: SUBSCRIPTION,
            })
    })

    it('follows the next cursor and appends older digests on loadMoreDigests', async () => {
        let page = 0
        useMocks({
            get: {
                '/api/environments/:team_id/pulse_digests/': () => {
                    page += 1
                    return page === 1
                        ? [200, { count: 2, next: '/api/environments/997/pulse_digests/?offset=1', results: [DIGEST] }]
                        : [200, { count: 2, next: null, results: [{ ...DIGEST, id: 'd2' }] }]
                },
            },
        })

        await expectLogic(logic, () => logic.actions.loadDigests())
            .toDispatchActions(['loadDigestsSuccess', 'setDigestsNext'])
            .toMatchValues({ digestsNext: '/api/environments/997/pulse_digests/?offset=1' })

        await expectLogic(logic, () => logic.actions.loadMoreDigests())
            .toDispatchActions(['loadMoreDigestsSuccess', 'setDigestsNext'])
            .toMatchValues({
                digests: [DIGEST, { ...DIGEST, id: 'd2' }],
                digestsNext: null,
            })
    })

    it('seeds subscriptionDraft from loaded subscription and patches locally', async () => {
        await expectLogic(logic, () => {
            logic.actions.loadSubscription()
        }).toDispatchActions(['loadSubscriptionSuccess'])

        await expectLogic(logic, () => {
            logic.actions.updateSubscriptionLocal({ frequency: 'daily', enabled: false })
        }).toMatchValues({
            subscriptionDraft: expect.objectContaining({
                frequency: 'daily',
                enabled: false,
                sensitivity: 'balanced',
            }),
        })
    })

    it('tracks expandedDigestId', async () => {
        await expectLogic(logic, () => {
            logic.actions.setExpandedDigestId('d9')
        }).toMatchValues({ expandedDigestId: 'd9' })
    })

    it('sets digestsError on loadDigestsFailure', async () => {
        useMocks({ get: { '/api/environments/:team_id/pulse_digests/': () => [500, {}] } })
        await expectLogic(logic, () => logic.actions.loadDigests()).toDispatchActions(['loadDigestsFailure'])
        expect(logic.values.digestsError).toBeTruthy()
    })

    it('sets findingsError on loadFindingsFailure', async () => {
        useMocks({ get: { '/api/environments/:team_id/pulse_findings/': () => [500, {}] } })
        await expectLogic(logic, () => logic.actions.loadFindings()).toDispatchActions(['loadFindingsFailure'])
        expect(logic.values.findingsError).toBeTruthy()
    })

    it('exposes subscriptionLoading while saving and applies preset locally', async () => {
        await expectLogic(logic, () => logic.actions.loadSubscription()).toDispatchActions(['loadSubscriptionSuccess'])

        logic.actions.updateSubscriptionLocal({
            sensitivity: 'sensitive',
            min_change_pct: 0.15,
            robust_z_threshold: 3.0,
        })
        expect(logic.values.subscriptionDraft?.min_change_pct).toBe(0.15)
        expect(logic.values.subscriptionDraft?.robust_z_threshold).toBe(3.0)

        await expectLogic(logic, () => logic.actions.saveSubscription())
            .toMatchValues({ subscriptionLoading: true })
            .toDispatchActions(['saveSubscriptionSuccess'])
            .toMatchValues({ subscriptionLoading: false })
    })

    it('loads watched candidates', async () => {
        await expectLogic(logic, () => logic.actions.loadWatched())
            .toDispatchActions(['loadWatchedSuccess'])
            .toMatchValues({ watchedCandidates: [WATCHED] })
    })

    it('reflects an in-progress scan and polls while the latest digest is generating', async () => {
        useMocks({
            get: {
                '/api/environments/:team_id/pulse_digests/': () => [
                    200,
                    { count: 1, results: [{ ...DIGEST, status: 'generating' }] },
                ],
            },
        })
        await expectLogic(logic, () => logic.actions.loadDigests()).toDispatchActions([
            'loadDigestsSuccess',
            'markScanInProgress',
            'pollScan',
        ])
        expect(logic.values.isScanInProgress).toBe(true)
    })

    it('does not flag scan in progress for a delivered digest', async () => {
        await expectLogic(logic, () => logic.actions.loadDigests()).toDispatchActions(['loadDigestsSuccess'])
        expect(logic.values.isScanInProgress).toBe(false)
    })

    it('starts polling and shows progress immediately after a manual scan trigger', async () => {
        useMocks({
            post: {
                '/api/environments/:team_id/pulse_digests/trigger_scan/': () => [202, { workflow_id: 'wf-1' }],
            },
        })
        await expectLogic(logic, () => logic.actions.triggerScan()).toDispatchActions([
            'triggerScanSuccess',
            'pollScan',
        ])
        expect(logic.values.isScanInProgress).toBe(true)
    })

    it('loads a past digest on getDigest', async () => {
        await expectLogic(logic, () => {
            logic.actions.setExpandedDigestId('d1')
            logic.actions.getDigest('d1')
        })
            .toDispatchActions(['getDigestSuccess'])
            .toMatchValues({
                expandedDigestId: 'd1',
                expandedDigest: expect.objectContaining({ id: 'd1' }),
            })
    })
})
