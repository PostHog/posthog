import { Meta } from '@storybook/react'
import { waitFor, within } from '@testing-library/dom'

import { FEATURE_FLAGS } from 'lib/constants'
import { App } from 'scenes/App'
import { sqlEditorLogic } from 'scenes/data-warehouse/editor/sqlEditorLogic'
import { urls } from 'scenes/urls'

import { DataVisualizationNode } from '~/queries/schema/schema-general'

import { expect, userEvent } from 'storybook/test'

import {
    Story,
    DISCARD_VIEW,
    DISCARD_INSIGHT,
    SAMPLE_SQL,
    sqlEditorStoryMeta,
} from './__mocks__/SQLEditorStoryFixtures'

const meta: Meta = { ...sqlEditorStoryMeta, component: App, title: 'Scenes-App/Data Warehouse/SQL Editor' }
export default meta

const waitForEditor = async (canvasElement: HTMLElement): Promise<void> => {
    await waitFor(() => expect(canvasElement.querySelector('.CodeEditor[data-editor-ready="true"]')).toBeVisible(), {
        timeout: 30000,
    })
}

// Keep the app shell at viewport height so snapshot capture does not resize and remount Monaco.
const pinEditorViewport = (): (() => void) => {
    document.body.classList.add('storybook-viewport-layout')
    return () => document.body.classList.remove('storybook-viewport-layout')
}

// Monaco takes focus when it mounts, so open the menu only after the editor is ready.
const openSaveMenu = async (canvasElement: HTMLElement, menuText = 'Save query as'): Promise<void> => {
    await waitForEditor(canvasElement)
    const body = within(canvasElement.ownerDocument.body)
    await waitFor(async () => {
        if (!body.queryByText(menuText)) {
            const trigger = canvasElement.querySelector<HTMLElement>('[data-attr="sql-editor-save-options-button"]')
            expect(trigger).toBeVisible()
            await userEvent.click(trigger!)
        }
        expect(body.getByText(menuText)).toBeVisible()
    })
}

// Waits for the insight to load and show its unsaved edit before it opens the save menu.
const openEditedInsightSaveMenu = async (canvasElement: HTMLElement, menuText = 'Save query as'): Promise<void> => {
    const canvas = within(canvasElement)
    await waitFor(
        () => expect(canvas.getByRole('button', { name: 'Discard changes' })).toHaveAttribute('aria-disabled', 'false'),
        { timeout: 30000 }
    )
    await openSaveMenu(canvasElement, menuText)
}

export const SaveAsFlowQuill: Story = {
    beforeEach: pinEditorViewport,
    parameters: {
        featureFlags: [FEATURE_FLAGS.SQL_EDITOR_SAVE_AS_CHOOSER, FEATURE_FLAGS.TODAY_RAIL_NAV],
        msw: {
            mocks: {
                get: {
                    '/api/projects/:team_id/warehouse_expressions/': { results: [] },
                    '/api/environments/:team_id/warehouse_expressions/': { results: [] },
                },
            },
        },
    },
    play: async ({ canvasElement }) => {
        await waitFor(() => expect(sqlEditorLogic({ tabId: 'default' }).values.queryInput).toBe(SAMPLE_SQL), {
            timeout: 30000,
        })
        await openSaveMenu(canvasElement)
    },
}

const discardMocks = {
    get: {
        '/api/projects/:team_id/warehouse_saved_queries/': [200, { results: [DISCARD_VIEW] }],
        '/api/:scope/:team_id/warehouse_saved_queries/:id/': [200, DISCARD_VIEW],
        '/api/:scope/:team_id/insights/': [200, { results: [DISCARD_INSIGHT] }],
        '/api/projects/:team_id/warehouse_expressions/': [200, { results: [] }],
        '/api/projects/:team_id/data_modeling_nodes/lineage/': [200, { nodes: [], edges: [] }],
        '/api/projects/:team_id/query_tab_state/user/': [200, { state: {} }],
    },
    patch: {
        '/api/:scope/:team_id/warehouse_saved_queries/:id/': async ({ request }: { request: Request }) => [
            200,
            { ...DISCARD_VIEW, ...(await request.json()) },
        ],
        '/api/:scope/:team_id/insights/:id/': async ({ request }: { request: Request }) => [
            200,
            { ...DISCARD_INSIGHT, ...(await request.json()) },
        ],
    },
}

const exerciseSaveConfirmation = async (canvasElement: HTMLElement, kind: 'view' | 'insight'): Promise<void> => {
    await waitForEditor(canvasElement)
    const canvas = within(canvasElement)
    const body = within(canvasElement.ownerDocument.body)
    const logic = sqlEditorLogic({ tabId: 'default' })
    const updateName = kind === 'view' ? 'Update view' : 'Update insight'
    await canvas.findByRole('button', { name: updateName })
    const update = (): HTMLElement => canvas.getByRole('button', { name: updateName })
    const confirmation = (): HTMLElement => body.getByRole('dialog', { name: 'Save query without running' })
    await waitFor(() => expect(update()).toHaveAttribute('aria-disabled', 'false'))
    await userEvent.click(update())
    await waitFor(() => expect(confirmation()).toBeVisible())
    await userEvent.click(body.getByText('Run latest', { exact: true }))
    await waitFor(() =>
        expect(body.queryByRole('dialog', { name: 'Save query without running' })).not.toBeInTheDocument()
    )
    await waitFor(() => expect(logic.values.lastRunQuery?.source.query).toBe('SELECT 2'))
    await waitFor(() => expect(update().querySelector('[data-attr="sql-editor-save-warning"]')).toBeNull())
    logic.actions.setQueryInput('SELECT 3')
    await waitFor(() => expect(update().querySelector('[data-attr="sql-editor-save-warning"]')).toBeVisible())
    await userEvent.click(update())
    await waitFor(() => expect(confirmation()).toBeVisible())
    await userEvent.click(body.getByText('Show diff', { exact: true }))
    await waitFor(() =>
        expect(body.queryByRole('dialog', { name: 'Save query without running' })).not.toBeInTheDocument()
    )
    await waitFor(() =>
        expect(logic.values.suggestionPayload).toMatchObject({
            originalValue: 'SELECT 1',
            suggestedValue: 'SELECT 3',
            acceptText: updateName,
        })
    )
    await userEvent.click(canvas.getByRole('button', { name: 'Cancel' }))
    await userEvent.click(canvas.getByRole('button', { name: 'Discard changes' }))
    await waitFor(() => expect(canvas.queryByText('Edited')).not.toBeInTheDocument())
    await expect(update()).toHaveAttribute('aria-disabled', 'true')
    if (kind === 'view') {
        logic.actions.setSourceQuery({
            ...logic.values.sourceQuery,
            source: { ...logic.values.sourceQuery.source, filters: { dateRange: { date_from: '-30d' } } },
        })
        await waitFor(() => expect(canvas.getByText('Edited')).toBeVisible())
        await expect(update()).toHaveAttribute('aria-disabled', 'false')
    }
    logic.actions.setQueryInput('SELECT 3')
    await waitFor(() => expect(update().querySelector('[data-attr="sql-editor-save-warning"]')).toBeVisible())
    await userEvent.click(update())
    await waitFor(() => expect(confirmation()).toBeVisible())
    await userEvent.click(body.getByText('Save anyway', { exact: true }))
    await waitFor(() =>
        expect(body.queryByRole('dialog', { name: 'Save query without running' })).not.toBeInTheDocument()
    )
    await waitFor(() =>
        expect(
            kind === 'view'
                ? logic.values.editingView?.query?.query
                : (logic.values.editingInsight?.query as DataVisualizationNode)?.source.query
        ).toBe('SELECT 3')
    )
    expect(logic.values.suggestionPayload).toBeNull()
    expect(canvas.queryByRole('button', { name: 'Cancel' })).not.toBeInTheDocument()
}

export const EditedView: Story = {
    parameters: {
        pageUrl: `${urls.sqlEditor({ view_id: DISCARD_VIEW.id })}#q=SELECT%202`,
        msw: { mocks: discardMocks },
    },
    play: async ({ canvasElement }) => exerciseSaveConfirmation(canvasElement, 'view'),
}

export const EditedViewQuill: Story = {
    ...EditedView,
    parameters: {
        ...EditedView.parameters,
        featureFlags: [FEATURE_FLAGS.TODAY_RAIL_NAV],
        testOptions: { snapshotBrowsers: [] },
    },
}

export const InsightSaveConfirmation: Story = {
    parameters: {
        pageUrl: `${urls.sqlEditor({ insightShortId: DISCARD_INSIGHT.short_id })}#q=SELECT%202`,
        msw: { mocks: discardMocks },
        testOptions: { snapshotBrowsers: [] },
    },
    play: async ({ canvasElement }) => exerciseSaveConfirmation(canvasElement, 'insight'),
}

export const InsightSaveConfirmationQuill: Story = {
    ...InsightSaveConfirmation,
    parameters: {
        ...InsightSaveConfirmation.parameters,
        featureFlags: [FEATURE_FLAGS.TODAY_RAIL_NAV],
    },
}

export const NewQuerySaveDiff: Story = {
    parameters: {
        pageUrl: urls.sqlEditor({ query: 'SELECT 2' }),
        featureFlags: [FEATURE_FLAGS.SQL_EDITOR_SAVE_AS_CHOOSER],
        testOptions: { snapshotBrowsers: [] },
    },
    play: async ({ canvasElement }) => {
        await waitForEditor(canvasElement)
        const logic = sqlEditorLogic({ tabId: 'default' })
        await waitFor(() => expect(logic.values.queryInput).toBe('SELECT 2'))
        await openSaveMenu(canvasElement)
        const body = within(canvasElement.ownerDocument.body)
        await userEvent.click(
            canvasElement.ownerDocument.querySelector<HTMLElement>('[data-attr="sql-editor-save-view-button"]')!
        )
        await waitFor(() => expect(body.getByRole('dialog', { name: 'Save query without running' })).toBeVisible())
        await userEvent.click(body.getByText('Show diff', { exact: true }))
        await waitFor(() => expect(canvasElement.querySelector('.monaco-diff-editor')).toBeVisible())
        expect(logic.values.originalQueryInput).toBe('')
        await userEvent.click(body.getByRole('button', { name: 'Cancel' }))
        expect(logic.values.queryInput).toBe('SELECT 2')
        expect(logic.values.suggestionPayload).toBeNull()
    },
}

export const EditedInsight: Story = {
    parameters: {
        featureFlags: [FEATURE_FLAGS.SQL_EDITOR_SAVE_AS_CHOOSER],
        pageUrl: `${urls.sqlEditor({ insightShortId: DISCARD_INSIGHT.short_id })}#q=SELECT%202`,
        msw: { mocks: discardMocks },
    },
    play: async ({ canvasElement }) => {
        await waitForEditor(canvasElement)
        const canvas = within(canvasElement)
        await canvas.findByRole('button', { name: 'Discard changes' }, { timeout: 15000 })
        await waitFor(() =>
            expect(canvas.getByRole('button', { name: 'Discard changes' })).toHaveAttribute('aria-disabled', 'false')
        )
        await waitFor(() => expect(canvas.getByText('Edited')).toBeVisible())
        await expect(canvas.getByRole('button', { name: 'Update insight' })).toHaveAttribute('aria-disabled', 'false')
        await expect(canvas.getByRole('button', { name: 'Continue in a notebook' })).toBeVisible()
        await openSaveMenu(canvasElement)
        const menu = within(canvasElement.ownerDocument.body)
        await expect(menu.queryByRole('menuitem', { name: 'Continue in a notebook' })).not.toBeInTheDocument()
        await expect(
            canvasElement.ownerDocument.querySelector('[data-attr="sql-editor-save-as-insight"]')
        ).toHaveAttribute('aria-disabled', 'false')
        await expect(
            canvasElement.ownerDocument.querySelector('[data-attr="sql-editor-save-view-button"]')
        ).toHaveAttribute('aria-disabled', 'false')
        await expect(
            canvasElement.ownerDocument.querySelector('[data-attr="sql-editor-save-as-endpoint"]')
        ).toHaveAttribute('aria-disabled', 'false')
        await userEvent.keyboard('{Escape}')
        await waitFor(() => expect(menu.queryByText('Save query as')).not.toBeInTheDocument())
        await userEvent.click(canvas.getByRole('button', { name: 'Stop editing insight' }))
        await waitFor(() => expect(canvas.queryByRole('button', { name: 'Update insight' })).not.toBeInTheDocument())
        await expect(canvas.getByRole('button', { name: 'Save as' })).toBeVisible()
        await expect(sqlEditorLogic({ tabId: 'default' }).values.queryInput).toEqual('SELECT 2')
    },
}

export const EditedInsightSaveAsFlow: Story = {
    beforeEach: pinEditorViewport,
    parameters: {
        featureFlags: [FEATURE_FLAGS.SQL_EDITOR_SAVE_AS_CHOOSER],
        pageUrl: `${urls.sqlEditor({ insightShortId: DISCARD_INSIGHT.short_id })}#q=SELECT%202`,
        msw: { mocks: discardMocks },
    },
    play: async ({ canvasElement }) => openEditedInsightSaveMenu(canvasElement),
}

export const EditedInsightSaveAsFlowQuill: Story = {
    beforeEach: pinEditorViewport,
    parameters: {
        featureFlags: [FEATURE_FLAGS.SQL_EDITOR_SAVE_AS_CHOOSER, FEATURE_FLAGS.TODAY_RAIL_NAV],
        pageUrl: `${urls.sqlEditor({ insightShortId: DISCARD_INSIGHT.short_id })}#q=SELECT%202`,
        msw: { mocks: discardMocks },
    },
    play: async ({ canvasElement }) => openEditedInsightSaveMenu(canvasElement),
}

export const EditedInsightLegacySaveMenu: Story = {
    beforeEach: pinEditorViewport,
    parameters: {
        featureFlags: { [FEATURE_FLAGS.SQL_EDITOR_SAVE_AS_CHOOSER]: false },
        pageUrl: `${urls.sqlEditor({ insightShortId: DISCARD_INSIGHT.short_id })}#q=SELECT%202`,
        msw: { mocks: discardMocks },
    },
    play: async ({ canvasElement }) => {
        await openEditedInsightSaveMenu(canvasElement, 'Save as new insight...')
        const menu = within(canvasElement.ownerDocument.body)
        await expect(await menu.findByRole('menuitem', { name: 'Save as new insight...' })).toHaveAttribute(
            'aria-disabled',
            'false'
        )
        await expect(menu.getByRole('menuitem', { name: 'Save as cohort...' })).toHaveAttribute('aria-disabled', 'true')
        await expect(menu.getByRole('menuitem', { name: 'Save as new view...' })).toHaveAttribute(
            'aria-disabled',
            'false'
        )
        await expect(menu.getByRole('menuitem', { name: 'Save as endpoint...' })).toHaveAttribute(
            'aria-disabled',
            'false'
        )
        await expect(menu.queryByText('Save query as')).not.toBeInTheDocument()
    },
}

export const EditedInsightLegacySaveMenuQuill: Story = {
    ...EditedInsightLegacySaveMenu,
    parameters: {
        ...EditedInsightLegacySaveMenu.parameters,
        featureFlags: {
            [FEATURE_FLAGS.SQL_EDITOR_SAVE_AS_CHOOSER]: false,
            [FEATURE_FLAGS.TODAY_RAIL_NAV]: true,
        },
    },
}
