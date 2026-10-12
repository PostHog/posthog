import type { Meta, StoryObj } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'

import { mswDecorator } from '~/mocks/browser'

import type { ExternalTableSyncSettingsApi } from 'products/data_warehouse/frontend/generated/api.schemas'
import { WarehouseTablesConfigureWarehouseSyncCreateBody } from 'products/data_warehouse/frontend/generated/api.zod'

import { ExternalTableSync } from './ExternalTableSync'

const SETTINGS: ExternalTableSyncSettingsApi = {
    available: true,
    unavailable_reason: null,
    enabled: false,
    interval_minutes: 60,
    status: 'disabled',
    last_synced_at: null,
    error: null,
}

const meta: Meta<typeof ExternalTableSync> = {
    title: 'Data Warehouse/ExternalTableSync',
    component: ExternalTableSync,
    args: { tableId: '00000000-0000-0000-0000-000000000001' },
    parameters: { featureFlags: [FEATURE_FLAGS.MANAGED_WAREHOUSE_EXTERNAL_TABLE_SYNC] },
    decorators: [
        (Story) => (
            <div className="p-4 max-w-2xl">
                <Story />
            </div>
        ),
    ],
}
export default meta
type Story = StoryObj<typeof meta>

function withSettings(settings: ExternalTableSyncSettingsApi): ReturnType<typeof mswDecorator> {
    return mswDecorator({
        get: {
            '/api/projects/:project_id/warehouse_tables/:id/warehouse_sync/': settings,
        },
        post: {
            '/api/projects/:project_id/warehouse_tables/:id/configure_warehouse_sync/': async ({ request }) => {
                const update = WarehouseTablesConfigureWarehouseSyncCreateBody.parse(await request.json())
                return { ...settings, ...update, status: update.enabled ? 'preparing' : 'disabled' }
            },
        },
    })
}

export const Off: Story = { decorators: [withSettings(SETTINGS)] }

export const Preparing: Story = {
    decorators: [withSettings({ ...SETTINGS, enabled: true, status: 'preparing' })],
}

export const ReadyInNarrowScene: Story = {
    decorators: [
        (Story) => (
            <div className="w-130">
                <Story />
            </div>
        ),
        withSettings({ ...SETTINGS, enabled: true, status: 'ready', last_synced_at: '2026-10-01T12:00:00Z' }),
    ],
}

export const RefreshFailed: Story = {
    decorators: [
        withSettings({
            ...SETTINGS,
            enabled: true,
            status: 'error',
            last_synced_at: '2026-10-01T12:00:00Z',
            error: 'The last refresh failed. Check the source location and read permissions, then save settings to retry.',
        }),
    ],
}

export const Unavailable: Story = {
    decorators: [
        withSettings({
            ...SETTINGS,
            available: false,
            unavailable_reason: 'Set up a managed warehouse for this project before enabling sync.',
        }),
    ],
}
