import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import posthog from 'posthog-js'
import { createElement } from 'react'

import { useMocks } from '~/mocks/jest'
import { NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

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
