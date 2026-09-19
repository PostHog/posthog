import { act, cleanup, render, screen } from '@testing-library/react'
import { BindLogic } from 'kea'
import { expectLogic } from 'kea-test-utils'

import { createCustomerJourney } from 'lib/customerJourneys/createCustomerJourney'
import * as journeyStarter from 'lib/customerJourneys/startCustomerJourney'
import { OutputPane } from 'scenes/data-warehouse/editor/OutputPane'
import { outputPaneLogic, OutputTab } from 'scenes/data-warehouse/editor/outputPaneLogic'
import { sqlEditorLogic } from 'scenes/data-warehouse/editor/sqlEditorLogic'
import { SQLEditorMode } from 'scenes/data-warehouse/editor/sqlEditorModes'
import { sceneLogic } from 'scenes/sceneLogic'
import { Scene } from 'scenes/sceneTypes'

import { useMocks } from '~/mocks/jest'
import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { dataVisualizationLogic } from '~/queries/nodes/DataVisualization/dataVisualizationLogic'
import { displayLogic } from '~/queries/nodes/DataVisualization/displayLogic'
import { performQuery } from '~/queries/query'
import { NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

jest.mock('~/queries/query', () => ({ ...jest.requireActual('~/queries/query'), performQuery: jest.fn() }))
jest.mock('lib/utils/kea-logic-builders', () => ({ permanentlyMount: () => () => {} }))

const tabId = 'synthetic-sensitive-editor-name'
const sourceQuery = {
    kind: NodeKind.DataVisualizationNode as const,
    source: { kind: NodeKind.HogQLQuery as const, query: "SELECT 'synthetic-sql-secret'" },
}
const key = `data-warehouse-editor-data-node-${tabId}`

function SqlResults({ biMode = false, mode }: { biMode?: boolean; mode?: SQLEditorMode }): JSX.Element {
    return (
        <BindLogic logic={dataNodeLogic} props={{ key }}>
            <BindLogic logic={sqlEditorLogic} props={{ tabId, ...(mode ? { mode } : {}) }}>
                <BindLogic logic={outputPaneLogic} props={{ tabId }}>
                    <BindLogic logic={dataVisualizationLogic} props={{ key, query: sourceQuery }}>
                        <BindLogic logic={displayLogic} props={{ key }}>
                            <OutputPane
                                tabId={tabId}
                                showToolbar={false}
                                biMode={biMode}
                                nativeQueryJourney={mode !== SQLEditorMode.Embedded}
                            />
                        </BindLogic>
                    </BindLogic>
                </BindLogic>
            </BindLogic>
        </BindLogic>
    )
}

describe('SQL request-to-results journey', () => {
    let capture: jest.Mock
    let resolve: (response: any) => void
    let editor: ReturnType<typeof sqlEditorLogic.build>
    let data: ReturnType<typeof dataNodeLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:team_id/warehouse_saved_queries/': { results: [] },
                '/api/projects/:team_id/external_data_sources/connections/': [],
                '/api/user_home_settings/@me/': {},
            },
        })
        initKeaTests()
        sceneLogic.mount()
        jest.spyOn(sceneLogic.actions, 'openScene').mockImplementation(() => {})
        jest.spyOn(sceneLogic.actions, 'loadScene').mockImplementation(() => {})
        sceneLogic.actions.setScene(Scene.SQLEditor, undefined, { params: { tabId }, searchParams: {}, hashParams: {} })
        capture = jest.fn()
        jest.spyOn(journeyStarter, 'startCustomerJourney').mockImplementation((options) =>
            createCustomerJourney(
                {
                    ...options,
                    attempt_id: options.attempt_id!,
                    region: 'US',
                    project_id: 1,
                    organization_id: 'synthetic-org',
                    registry_version: 'test',
                },
                { now: () => 1, capture, visibility: { getState: () => 'visible', subscribe: () => () => {} } }
            )
        )
        ;(performQuery as jest.Mock).mockImplementation((query) =>
            query.kind === NodeKind.HogQLQuery
                ? new Promise((yes) => {
                      resolve = yes
                  })
                : Promise.resolve({ tables: {}, joins: [] })
        )
        editor = sqlEditorLogic({ tabId, mode: SQLEditorMode.FullScene })
        editor.mount()
        editor.actions.setSourceQuery(sourceQuery)
        editor.actions.setQueryInput(sourceQuery.source.query)
        data = dataNodeLogic({
            key,
            query: sourceQuery.source,
            queryJourney: editor.values.queryJourney,
            autoLoad: false,
        })
        data.mount()
    })

    afterEach(() => {
        cleanup()
        data.unmount()
        editor.unmount()
        sceneLogic.unmount()
        jest.restoreAllMocks()
    })

    it.each([{ results: [] }, { results: [['synthetic-result-secret']] }])(
        'waits for the real results commit %j',
        async ({ results }) => {
            const view = render(<SqlResults />)
            act(() => editor.actions.runQuery())
            expect(capture.mock.calls).toEqual([
                ['customer_journey_started', expect.objectContaining({ journey_name: 'sql_run' })],
            ])
            await act(async () => {
                await Promise.resolve()
                resolve({ results, columns: ['synthetic_column'], types: [['synthetic_column', 'String']] })
                await expectLogic(data).toFinishAllListeners()
            })
            const queryId = capture.mock.calls[0][1].attempt_id
            expect(jest.mocked(performQuery).mock.calls.some((call) => call[3] === queryId)).toBe(true)
            expect(capture.mock.calls[0][1].client_query_id).toBe(queryId)
            expect(capture.mock.calls.at(-1)?.[1]).toMatchObject({
                outcome: 'usable',
                first_useful_ms: 0,
                client_query_id: queryId,
            })
            expect(JSON.stringify(capture.mock.calls)).not.toMatch(
                /synthetic-sql-secret|synthetic-result-secret|synthetic_column|synthetic-sensitive-editor-name/
            )
            const committedSurface =
                results.length === 0 ? screen.getByText('Query produced no results') : screen.getByRole('grid')
            expect(committedSurface).toBeTruthy()
            view.unmount()
        }
    )

    it('excludes pre-observer automatic execution without delaying or backdating it', async () => {
        editor.actions.runQuery()
        await Promise.resolve()
        const view = render(<SqlResults />)
        await act(async () => {
            resolve({ results: [], columns: [], types: [] })
            await expectLogic(data).toFinishAllListeners()
        })
        expect(capture).not.toHaveBeenCalled()
        act(() => editor.actions.runQuery(undefined, true))
        expect(capture.mock.calls).toEqual([['customer_journey_started', expect.anything()]])
        view.unmount()
        expect(capture.mock.calls.at(-1)?.[1].outcome).toBe('observation_stopped')
    })

    it.each(['visualization', 'bi', 'mode', 'scene', 'tab', 'unmount'])(
        'stops observation when Results loses %s ownership',
        async (loss) => {
            const view = render(<SqlResults />)
            act(() => editor.actions.runQuery())
            await act(async () => {
                await Promise.resolve()
            })
            act(() => {
                if (loss === 'visualization') {
                    outputPaneLogic({ tabId }).actions.setActiveTab(OutputTab.Visualization)
                } else if (loss === 'bi') {
                    view.rerender(<SqlResults biMode />)
                } else if (loss === 'mode') {
                    view.rerender(<SqlResults mode={SQLEditorMode.Embedded} />)
                } else if (loss === 'scene') {
                    sceneLogic.actions.setScene(Scene.Dashboards, undefined, {
                        params: {},
                        searchParams: {},
                        hashParams: {},
                    })
                } else if (loss === 'tab') {
                    sceneLogic.actions.setScene(Scene.SQLEditor, undefined, {
                        params: { tabId: 'another' },
                        searchParams: {},
                        hashParams: {},
                    })
                } else {
                    view.unmount()
                }
            })
            expect(capture.mock.calls.at(-1)?.[1].outcome).toBe('observation_stopped')
            view.unmount()
        }
    )

    it.each(['visualization', 'bi', 'embedded', 'custom'])('excludes executions from %s hosts', async (host) => {
        if (host === 'visualization') {
            outputPaneLogic({ tabId }).actions.setActiveTab(OutputTab.Visualization)
        }
        if (host === 'embedded') {
            sqlEditorLogic({ tabId, mode: SQLEditorMode.Embedded })
        }
        if (host === 'custom') {
            sqlEditorLogic({ tabId, nativeQueryJourney: false })
        }
        const view = render(<SqlResults biMode={host === 'bi'} />)
        act(() => editor.actions.runQuery())
        await act(async () => {
            await Promise.resolve()
            resolve({ results: [], columns: [], types: [] })
            await expectLogic(data).toFinishAllListeners()
        })
        expect(capture).not.toHaveBeenCalled()
        expect(data.values.response).toMatchObject({ results: [] })
        view.unmount()
    })

    it('finishes once in Both and does not leak a returned query error', async () => {
        outputPaneLogic({ tabId }).actions.setActiveTab(OutputTab.Both)
        const view = render(<SqlResults />)
        act(() => editor.actions.runQuery())
        await act(async () => {
            await Promise.resolve()
            resolve({ results: [], columns: [], types: [] })
            await expectLogic(data).toFinishAllListeners()
        })
        expect(
            capture.mock.calls.filter(
                ([event, properties]) => event === 'customer_journey_finished' && properties.outcome === 'usable'
            )
        ).toHaveLength(1)
        act(() => editor.actions.runQuery())
        await act(async () => {
            await Promise.resolve()
            resolve({ results: [], error: 'synthetic-error-secret' })
            await expectLogic(data).toFinishAllListeners()
        })
        expect(capture.mock.calls.at(-1)?.[1]).toMatchObject({ outcome: 'failed', error_type: 'query_error' })
        expect(capture.mock.calls.at(-1)?.[1]).not.toHaveProperty('first_useful_ms')
        expect(JSON.stringify(capture.mock.calls)).not.toContain('synthetic-error-secret')
        view.unmount()
    })

    it.each([null, { result: [] }])('never claims unusable payload %j', async (response) => {
        const view = render(<SqlResults />)
        act(() => editor.actions.runQuery())
        await act(async () => {
            await Promise.resolve()
            resolve(response)
            await expectLogic(data).toFinishAllListeners()
        })
        expect(capture.mock.calls.filter(([event]) => event === 'customer_journey_finished')).toEqual([])
        view.unmount()
        expect(capture.mock.calls.at(-1)?.[1].outcome).toBe('observation_stopped')
    })
})
