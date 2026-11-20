import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import posthog from 'posthog-js'
import { createElement } from 'react'

import { useMocks } from '~/mocks/jest'
import { NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import { notebookCohortFilterLogic } from 'products/notebooks/frontend/notebookCohortFilterLogic'

import { notebookLogic } from '../Notebook/notebookLogic'
import { NotebookNodeType } from '../types'
import { NotebookNodeContext } from './NotebookNodeContext'
import { notebookNodeLogic } from './notebookNodeLogic'
import { NotebookNodeQuery, getNotebookSqlOutputToolbarVisibility } from './NotebookNodeQuery'

describe('NotebookNodeQuery', () => {
    it.each([200, 500])('refreshes the displayed insight query and reports HTTP %i', async (status) => {
        const refreshModes: unknown[] = []
        useMocks({
            post: {
                '/api/projects/:project_id/query/TrendsQuery/': async ({ request }) => {
                    const { refresh } = (await request.json()) as { refresh?: string }
                    refreshModes.push(refresh)
                    if (refresh === 'force_blocking' && status === 500) {
                        return [500, { detail: 'Query failed' }]
                    }
                    return [200, { results: [], last_refresh: '2020-01-01T00:00:00Z' }]
                },
            },
        })
        initKeaTests()
        const capture = jest.spyOn(posthog, 'capture')
        const notebook = notebookLogic({ shortId: 'template-refresh-test' })
        const unmountNotebook = notebook.mount()
        const attributes = {
            nodeId: 'refresh-insight',
            isDefaultFilterApplied: true,
            query: {
                kind: NodeKind.InsightVizNode as const,
                source: {
                    kind: NodeKind.TrendsQuery as const,
                    series: [{ kind: NodeKind.EventsNode as const, event: '$pageview' }],
                },
            },
        }
        const node = notebookNodeLogic({
            notebookLogic: notebook,
            nodeType: NotebookNodeType.Query,
            titlePlaceholder: 'Insight',
            attributes,
            updateAttributes: jest.fn(),
        })
        const unmountNode = node.mount()
        try {
            render(
                createElement(
                    NotebookNodeContext.Provider,
                    { value: node },
                    createElement(NotebookNodeQuery.Component, { attributes, updateAttributes: jest.fn() })
                )
            )
            fireEvent.click(await screen.findByText('Refresh'))
            await waitFor(() => expect(refreshModes).toContain('force_blocking'))
            await waitFor(() =>
                expect(capture).toHaveBeenCalledWith('notebook insight refresh completed', {
                    notebook_id: 'template-refresh-test',
                    node_id: 'refresh-insight',
                    success: status === 200,
                })
            )
        } finally {
            cleanup()
            unmountNode()
            unmountNotebook()
            capture.mockRestore()
        }
    })

    it('requeries the insight when a viewer switches cohorts without editing the notebook', async () => {
        const requested: unknown[] = []
        useMocks({
            post: {
                '/api/projects/:project_id/query/TrendsQuery/': async ({ request }) => {
                    const { query } = (await request.json()) as { query: { properties?: unknown } }
                    requested.push(query.properties)
                    return [200, { results: [], last_refresh: '2026-01-01T00:00:00Z' }]
                },
            },
        })
        initKeaTests()
        const shortId = 'template-cohort-preview'
        const notebook = notebookLogic({ shortId })
        const preview = notebookCohortFilterLogic({ shortId })
        const attributes = {
            nodeId: 'signups',
            isDefaultFilterApplied: true,
            query: {
                kind: NodeKind.InsightVizNode as const,
                source: {
                    kind: NodeKind.TrendsQuery as const,
                    series: [{ kind: NodeKind.EventsNode as const, event: 'signup' }],
                },
            },
        }
        const originalAttributes = structuredClone(attributes)
        const updateAttributes = (changes: object): void => {
            Object.assign(attributes, changes)
        }
        const node = notebookNodeLogic({
            notebookLogic: notebook,
            nodeType: NotebookNodeType.Query,
            titlePlaceholder: 'Signups',
            attributes,
            updateAttributes,
        })
        const unmountNotebook = notebook.mount()
        const unmountNode = node.mount()
        const unmountPreview = preview.mount()
        try {
            preview.actions.setPreviewCohort({ id: 17, name: 'First cohort' })
            render(
                createElement(
                    NotebookNodeContext.Provider,
                    { value: node },
                    createElement(NotebookNodeQuery.Component, { attributes, updateAttributes })
                )
            )
            await waitFor(() =>
                expect(requested).toContainEqual([{ type: 'cohort', key: 'id', operator: 'in', value: 17 }])
            )
            act(() => preview.actions.setPreviewCohort({ id: 42, name: 'Second cohort' }))
            await waitFor(() =>
                expect(requested).toContainEqual([{ type: 'cohort', key: 'id', operator: 'in', value: 42 }])
            )
            expect(attributes).toEqual(originalAttributes)
            act(() => preview.actions.setPreviewCohort(null))
            expect(await screen.findByText('Refresh')).toBeTruthy()
        } finally {
            cleanup()
            unmountPreview()
            unmountNode()
            unmountNotebook()
        }
    })

    const markdownPanelState = ({
        filters,
        results,
    }: {
        filters: boolean
        results: boolean
    }): NonNullable<Parameters<typeof getNotebookSqlOutputToolbarVisibility>[0]['componentPanelState']> => ({
        componentPanels: { filters, results },
        showEditPanel: filters,
        showViewPanel: results,
    })

    it('shows SQL output tabs only when markdown edit and view panels are both open', () => {
        expect(
            getNotebookSqlOutputToolbarVisibility({
                componentPanelState: markdownPanelState({ filters: true, results: true }),
                expanded: false,
                isEditing: false,
            })
        ).toBe(true)

        expect(
            getNotebookSqlOutputToolbarVisibility({
                componentPanelState: markdownPanelState({ filters: true, results: false }),
                expanded: true,
                isEditing: true,
            })
        ).toBe(false)

        expect(
            getNotebookSqlOutputToolbarVisibility({
                componentPanelState: markdownPanelState({ filters: false, results: true }),
                expanded: true,
                isEditing: true,
            })
        ).toBe(false)

        expect(
            getNotebookSqlOutputToolbarVisibility({
                componentPanelState: markdownPanelState({ filters: false, results: false }),
                expanded: true,
                isEditing: true,
            })
        ).toBe(false)
    })

    it('falls back to legacy expanded and editing state outside markdown notebooks', () => {
        expect(
            getNotebookSqlOutputToolbarVisibility({
                componentPanelState: null,
                expanded: true,
                isEditing: true,
            })
        ).toBe(true)
        expect(
            getNotebookSqlOutputToolbarVisibility({
                componentPanelState: null,
                expanded: true,
                isEditing: false,
            })
        ).toBe(false)
        expect(
            getNotebookSqlOutputToolbarVisibility({
                componentPanelState: null,
                expanded: false,
                isEditing: true,
            })
        ).toBe(false)
    })
})
