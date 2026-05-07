import type { Meta, StoryObj } from '@storybook/react'
import { within } from '@testing-library/dom'
import userEvent from '@testing-library/user-event'

import { useStorybookMocks } from '~/mocks/browser'

import { BulkUpdateTagsButton } from './BulkUpdateTagsButton'

const RESOURCE = 'feature_flags' as const
const SELECTED_IDS = [1, 2, 3]

const meta: Meta<typeof BulkUpdateTagsButton> = {
    title: 'Components/BulkUpdateTagsButton',
    component: BulkUpdateTagsButton,
    parameters: { layout: 'centered' },
    decorators: [
        function MocksDecorator(Story) {
            useStorybookMocks({
                get: {
                    '/api/projects/:team_id/tags': ['production', 'staging', 'beta', 'internal'],
                },
            })
            return <Story />
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
    const segment = await canvas.findByRole('radio', { name: action })
    await userEvent.click(segment)
}

export const Closed: Story = {
    parameters: { testOptions: { waitForSelector: '[role="button"]' } },
}

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
