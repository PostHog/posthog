import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import { BindLogic } from 'kea'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { expectLogic } from '~/test/keaTestUtils'

import { dataCatalogMetricSceneLogic } from '../dataCatalogMetricSceneLogic'
import { MetricTestsTab } from './MetricTestsTab'
import { QuillMetricTestsTab } from './QuillMetricTestsTab'

const TABS = [
    ['Lemon', MetricTestsTab, /queries \{metric\}/],
    ['quill', QuillMetricTestsTab, /No checks on Daily signups yet/],
] as const

describe('MetricTestsTab', () => {
    afterEach(cleanup)
    it.each(
        TABS.flatMap(([label, Tab, emptyState]) =>
            ['HogQLQuery', 'MarkdownDefinition'].map((kind) => [label, kind, Tab, emptyState] as const)
        )
    )('%s tab offers the check editor only for SQL metrics (%s)', async (_label, kind, Tab, emptyState) => {
        useMocks({
            get: {
                '/api/projects/:team_id/data_catalog/metrics/signups/': {
                    id: 'metric-1',
                    name: 'signups',
                    display_name: 'Daily signups',
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
                <Tab />
            </BindLogic>
        )
        if (kind === 'HogQLQuery') {
            expect(await screen.findByText(emptyState)).toBeInTheDocument()
            expect(screen.queryByText('Run automatically')).not.toBeInTheDocument()
        } else {
            expect(await screen.findByText(/Tests are available for SQL metrics only/)).toBeInTheDocument()
            expect(screen.queryByText('New check')).not.toBeInTheDocument()
        }
        logic.unmount()
    })

    it.each(TABS.map(([label, Tab]) => [label, Tab] as const))(
        '%s tab lists the checks a metric kept after its definition stopped being SQL',
        async (_label, Tab) => {
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
                    <Tab />
                </BindLogic>
            )
            expect(await screen.findByText('Signups are positive')).toBeInTheDocument()
            expect(screen.getByText(/definition is not SQL/)).toBeInTheDocument()
            expect(screen.getByText('Run automatically')).toBeInTheDocument()
            expect(screen.getByText('New check').closest('button')).toHaveAttribute('aria-disabled', 'true')
            logic.unmount()
        }
    )
})
