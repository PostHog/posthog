import { urls } from 'scenes/urls'

import { makeTraceCluster } from './testFixtures'
import { toClustersChip } from './toClustersChip'

describe('toClustersChip', () => {
    it.each([
        ['nothing loaded', null],
        ['no clusters', []],
    ])('shows no chip with %s', (_name, clusters) => {
        expect(toClustersChip(clusters)).toBeNull()
    })

    it('leads with the first cluster and links each cluster to its page', () => {
        const chip = toClustersChip([
            makeTraceCluster({
                runId: '1_trace_20260902_030000_job a',
                runAt: '2026-09-02T03:40:00Z',
                clusterId: 3,
                title: 'Billing questions',
            }),
            makeTraceCluster({
                runId: '1_trace_20260901_030000',
                clusterId: -1,
                title: null,
                jobName: null,
                isOutlier: true,
            }),
            makeTraceCluster({ runId: '1_trace_20260901_040000', clusterId: 7, title: null }),
        ])

        expect(chip?.first).toMatchObject({
            label: 'Billing questions',
            runAt: '2026-09-02T03:40:00Z',
            href: urls.aiObservabilityCluster('1_trace_20260902_030000_job a', 3),
        })
        expect(chip?.others.map(({ label, href }) => ({ label, href }))).toEqual([
            { label: 'Outliers', href: urls.aiObservabilityCluster('1_trace_20260901_030000', -1) },
            { label: 'Cluster 7', href: urls.aiObservabilityCluster('1_trace_20260901_040000', 7) },
        ])
    })
})
