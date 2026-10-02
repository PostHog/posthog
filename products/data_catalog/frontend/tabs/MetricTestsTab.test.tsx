import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import { BindLogic } from 'kea'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { expectLogic } from '~/test/keaTestUtils'

import { dataCatalogMetricSceneLogic } from '../dataCatalogMetricSceneLogic'
import { MetricTestsTab } from './MetricTestsTab'

describe('MetricTestsTab', () => {
    afterEach(cleanup)
    it.each(['HogQLQuery', 'MarkdownDefinition'])('offers the check editor only for SQL metrics (%s)', async (kind) => {
        useMocks({
            get: {
                '/api/projects/:team_id/data_catalog/metrics/signups/': {
                    id: 'metric-1',
                    name: 'signups',
                    definition_kind: kind,
                },
                '/api/projects/:team_id/data_quality_checks/': { results: [] },
                '/api/projects/:team_id/data_quality_checks/health/': [],
                '/api/projects/:team_id/data_quality_runs/': { results: [] },
            },
        })
        initKeaTests()
        const logic = dataCatalogMetricSceneLogic({ name: 'signups' })
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadMetricSuccess'])
        render(
            <BindLogic logic={dataCatalogMetricSceneLogic} props={{ name: 'signups' }}>
                <MetricTestsTab />
            </BindLogic>
        )
        if (kind === 'HogQLQuery') {
            expect(await screen.findByText('Add your first check')).toBeInTheDocument()
            expect(screen.getByText(/queries \{metric\}/)).toBeInTheDocument()
            expect(screen.queryByText('Run automatically')).not.toBeInTheDocument()
        } else {
            expect(await screen.findByText(/Tests are available for SQL metrics only/)).toBeInTheDocument()
            expect(screen.queryByText('New check')).not.toBeInTheDocument()
        }
        logic.unmount()
    })

    it('lists the checks a metric kept after its definition stopped being SQL', async () => {
        useMocks({
            get: {
                '/api/projects/:team_id/data_catalog/metrics/signups/': {
                    id: 'metric-1',
                    name: 'signups',
                    definition_kind: 'MarkdownDefinition',
                },
                '/api/projects/:team_id/data_quality_checks/': {
                    results: [
                        {
                            id: 'check-1',
                            name: 'Signups are positive',
                            check_type: 'custom_sql',
                            enabled: true,
                            severity: 'error',
                            last_status: 'errored',
                            config: {},
                            tags: [],
                        },
                    ],
                },
                '/api/projects/:team_id/data_quality_checks/health/': [
                    {
                        subject_type: 'metric',
                        subject_uuid: 'metric-1',
                        health: 'failing',
                        checks_total: 1,
                        checks_failing: 1,
                    },
                ],
                '/api/projects/:team_id/data_quality_checks/schedule/': {
                    id: 'schedule-1',
                    enabled: true,
                    interval: '24hour',
                    next_run_at: null,
                    last_run_at: null,
                    last_suite_run: null,
                },
                '/api/projects/:team_id/data_quality_runs/': { results: [] },
            },
        })
        initKeaTests()
        const logic = dataCatalogMetricSceneLogic({ name: 'signups' })
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadMetricSuccess'])
        render(
            <BindLogic logic={dataCatalogMetricSceneLogic} props={{ name: 'signups' }}>
                <MetricTestsTab />
            </BindLogic>
        )
        expect(await screen.findByText('Signups are positive')).toBeInTheDocument()
        expect(screen.getByText(/definition is not SQL/)).toBeInTheDocument()
        expect(screen.getByText('Run automatically')).toBeInTheDocument()
        expect(screen.getByText('New check').closest('button')).toHaveAttribute('aria-disabled', 'true')
        logic.unmount()
    })
})
