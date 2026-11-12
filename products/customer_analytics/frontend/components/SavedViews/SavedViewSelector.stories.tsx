import type { Meta, StoryObj } from '@storybook/react'
import { within } from '@testing-library/dom'
import userEvent from '@testing-library/user-event'

import { LemonInput } from '@posthog/lemon-ui'

import type { ColumnConfigurationApi } from 'products/product_analytics/frontend/generated/api.schemas'

import { expect, fn } from 'storybook/test'

import { SavedViewSelector } from './SavedViewSelector'

const view: ColumnConfigurationApi = {
    id: 'example-view',
    context_key: 'example-notes',
    name: 'Renewal notes',
    visibility: 'shared',
    created_by: null,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
}

const meta: Meta<typeof SavedViewSelector> = {
    title: 'Customer Analytics/Saved views/Selector',
    component: SavedViewSelector,
    parameters: { layout: 'padded' },
    args: {
        views: [view],
        currentView: view,
        currentViewId: view.id,
        isDirty: false,
        viewsLoading: false,
        viewsLoaded: true,
        viewsLoadError: false,
        onSelect: () => {},
        onUpdate: () => {},
        onEdit: () => {},
        onDelete: () => {},
        onCreate: () => {},
        onRetry: () => {},
        dataAttrPrefix: 'example',
        renderViewTooltip: () => (
            <div>
                Tags: renewal
                <br />
                Sort: Last modified, newest first
            </div>
        ),
    },
}
export default meta

type Story = StoryObj<typeof SavedViewSelector>

export const Selected: Story = {}
export const NoViews: Story = { args: { views: [], currentView: null, currentViewId: null } }
export const Unselected: Story = { args: { currentView: null, currentViewId: null } }
export const LoadingRememberedView: Story = {
    args: {
        views: [],
        currentView: null,
        currentViewName: view.name,
        viewsLoading: true,
        viewsLoaded: false,
        awaitingSavedView: true,
    },
    parameters: { testOptions: { waitForLoadersToDisappear: false } },
}
export const Menu: Story = {
    play: async ({ canvasElement }) => {
        await userEvent.click(await within(canvasElement).findByText('Renewal notes'))
        await within(document.body).findByText('Save as new view...')
    },
}
export const ResetView: Story = {
    args: { resetOption: { label: 'All notes', onClick: fn() } },
    parameters: { testOptions: { snapshotBrowsers: [] } },
    play: async ({ canvasElement, args }) => {
        await userEvent.click(await within(canvasElement).findByText('Renewal notes'))
        await userEvent.click(await within(document.body).findByText('All notes'))
        await expect(args.resetOption?.onClick).toHaveBeenCalledTimes(1)
    },
}
export const Narrow: Story = {
    args: { currentView: { ...view, name: 'Renewal notes with a longer saved view name' }, isDirty: true },
    render: (args) => (
        <div className="w-80 max-w-full flex flex-wrap gap-2 items-center">
            <LemonInput type="search" placeholder="Search notes" size="small" />
            <SavedViewSelector {...args} />
        </div>
    ),
}
