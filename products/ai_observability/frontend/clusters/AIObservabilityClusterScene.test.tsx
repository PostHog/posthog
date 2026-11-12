import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { BindLogic } from 'kea'
import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { teamLogic } from 'scenes/teamLogic'

import { initKeaTests } from '~/test/init'

import { traceDrawerLogic } from '../redesign/trace/traceDrawerLogic'
import { traceViewHostLogic } from '../redesign/trace/traceViewHostLogic'
import { AIObservabilityClusterScene } from './AIObservabilityClusterScene'
import { clusterDetailLogic } from './clusterDetailLogic'
import { Cluster } from './types'

const RUN_ID = 'team_2025-01-05'
const PROPS = { runId: RUN_ID, clusterId: 0 }

function clusterAtLevel(level: string): { cluster: Cluster } {
    const info = (traceId: string, timestamp: string, generationId?: string): Cluster['traces'][string] => ({
        distance_to_centroid: 0.1,
        rank: 0,
        x: 0,
        y: 0,
        timestamp,
        trace_id: traceId,
        generation_id: generationId,
    })
    return {
        cluster: {
            cluster_id: 0,
            size: 2,
            title: 'Cluster',
            description: '',
            centroid: [1],
            centroid_x: 0,
            centroid_y: 0,
            traces: {
                'key-1': info('trace-1', '2025-01-05T10:00:00Z', level === 'generation' ? 'gen-1' : undefined),
                'key-2': info('trace-2', '2025-01-05T11:00:00Z', level === 'generation' ? 'gen-2' : undefined),
            },
        },
    }
}

describe('AIObservabilityClusterScene', () => {
    let logic: ReturnType<typeof clusterDetailLogic.build>

    async function mountScene(level: string): Promise<void> {
        const { cluster } = clusterAtLevel(level)
        initKeaTests()
        localStorage.clear()
        jest.spyOn(api, 'queryHogQL').mockImplementation(async (query) =>
            String(query).includes('$ai_clusters')
                ? { results: [[RUN_ID, 'a', 'b', JSON.stringify([cluster]), '2025-01-05T00:00:00Z', level]] }
                : { results: [] }
        )
        teamLogic.mount()
        await expectLogic(teamLogic).toFinishAllListeners()
        featureFlagLogic.mount()
        router.actions.push('/ai-observability/clusters/' + RUN_ID + '/0')
        logic = clusterDetailLogic(PROPS)
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        render(
            <BindLogic logic={clusterDetailLogic} props={PROPS}>
                <AIObservabilityClusterScene />
            </BindLogic>
        )
        await waitFor(() => expect(screen.getAllByText(/^View (trace|generation) →$/)).toHaveLength(2))
    }

    afterEach(async () => {
        await expectLogic(teamLogic).toFinishAllListeners()
        cleanup()
        logic.unmount()
        jest.restoreAllMocks()
    })

    it('opens a trace-level member on its trace, and steps through the page rows', async () => {
        await mountScene('trace')

        fireEvent.click(screen.getAllByText('View trace →')[0])

        expect(router.values.searchParams).toEqual({ trace: 'key-1', ts: '2025-01-05T10:00:00.000Z' })
        const host = traceViewHostLogic({ hostId: traceDrawerLogic({ listId: 'cluster-traces' }).values.hostId })
        expect(host.values.openingMode).toBe('summary')
        expect(traceDrawerLogic({ listId: 'cluster-traces' }).values.rows.map((row) => row.traceId)).toEqual([
            'key-1',
            'key-2',
        ])
    })

    it('opens a generation-level member on its step', async () => {
        await mountScene('generation')

        fireEvent.click(screen.getAllByText('View generation →')[1])

        expect(router.values.searchParams).toEqual({ trace: 'trace-2', ts: '2025-01-05T11:00:00.000Z', step: 'gen-2' })
        const host = traceViewHostLogic({ hostId: traceDrawerLogic({ listId: 'cluster-traces' }).values.hostId })
        expect(host.values.requestedStepId).toBe('gen-2')
    })
})
