import { Meta, StoryObj } from '@storybook/react'
import { waitFor } from '@testing-library/dom'

import { FEATURE_FLAGS } from 'lib/constants'
import { urls } from 'scenes/urls'

import { userEvent } from 'storybook/test'

import { TodayWarehouseHeader } from './TodayWarehouseHeader'

const meta: Meta = {
    title: 'Layout/Today/Warehouse header',
    render: () => (
        <div data-quill>
            <TodayWarehouseHeader />
        </div>
    ),
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        featureFlags: [
            FEATURE_FLAGS.TODAY_RAIL_NAV,
            FEATURE_FLAGS.TODAY_RAIL_WAREHOUSE,
            FEATURE_FLAGS.SQL_EDITOR_BI_MODE,
        ],
        pageUrl: urls.sqlEditor(),
    },
}
export default meta

type Story = StoryObj<typeof meta>

export const OnSqlEditor: Story = {}

export const MenuOpen: Story = {
    play: async ({ canvasElement }): Promise<void> => {
        const trigger = await waitFor(
            () => {
                const button = canvasElement.querySelector<HTMLElement>('[data-attr="today-warehouse-menu"]')
                if (!button) {
                    throw new Error('Warehouse menu trigger not yet rendered')
                }
                return button
            },
            { timeout: 2000 }
        )
        await userEvent.click(trigger)
    },
}
