import { Meta, StoryObj } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'
import { urls } from 'scenes/urls'

import { TodayWarehouseSidebar } from './TodayWarehouseSidebar'

const meta: Meta = {
    title: 'Layout/Today/Warehouse sidebar',
    render: () => (
        <div data-quill className="flex h-[640px] w-56 flex-col bg-surface-primary">
            <TodayWarehouseSidebar />
        </div>
    ),
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        featureFlags: [
            FEATURE_FLAGS.TODAY_RAIL_NAV,
            FEATURE_FLAGS.TODAY_RAIL_WAREHOUSE,
            FEATURE_FLAGS.MANAGED_WAREHOUSE_CONSOLE,
        ],
        pageUrl: urls.warehouseUsage(),
    },
}
export default meta

type Story = StoryObj<typeof meta>

export const OnUsagePage: Story = {}
