import type { Meta, StoryObj } from '@storybook/react'
import { screen, within } from '@testing-library/dom'
import userEvent from '@testing-library/user-event'

import { useStorybookMocks } from '~/mocks/browser'

import { BulkUpdateTagsButton } from './BulkUpdateTagsButton'

const RESOURCE = 'feature_flags' as const
const SELECTED_IDS = [1, 2, 3]

const meta: Meta<typeof BulkUpdateTagsButton> = {
    title: 'Components/BulkUpdateTagsButton',
    component: BulkUpdateTagsButton,
    parameters: { layout: 'fullscreen' },
    decorators: [
        function MocksDecorator(Story) {
            useStorybookMocks({
                get: {
                    '/api/projects/:team_id/tags': ['production', 'staging', 'beta', 'internal'],
                },
            })
            // Reserve enough viewport for the popover (placement: 'bottom-end') to render
            // entirely within the snapshot. The popover content is ~320px wide and ~360px tall.
            return (
                <div className="flex items-start justify-end p-4" style={{ minHeight: 480, minWidth: 420 }}>
                    <Story />
                </div>
            )
        },
    ],
    args: { resource: RESOURCE, selectedIds: SELECTED_IDS },
}
export default meta

type Story = StoryObj<typeof BulkUpdateTagsButton>

async function openAndPickAction(canvasElement: HTMLElement, action: 'Add' | 'Remove' | 'Replace all'): Promise<void> {
    const canvas = within(canvasElement)
    const trigger = await canvas.findByRole('button', { name: 'Update tags' })
    await userEvent.click(trigger)
    // Popover overlay renders to a portal, so query at the document level rather than canvas.
    const segment = await screen.findByRole('button', { name: action })
    await userEvent.click(segment)
}

export const Closed: Story = {}

export const AddMode: Story = {
    play: async ({ canvasElement }) => {
        await openAndPickAction(canvasElement, 'Add')
    },
}

export const RemoveMode: Story = {
    play: async ({ canvasElement }) => {
        await openAndPickAction(canvasElement, 'Remove')
    },
}

export const ReplaceMode: Story = {
    play: async ({ canvasElement }) => {
        await openAndPickAction(canvasElement, 'Replace all')
    },
}
