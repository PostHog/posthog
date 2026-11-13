import type { Meta, StoryObj } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'
import type { Mocks } from '~/mocks/utils'

import { catalogStoryMocks, inMainContent } from '../catalogStoryFixtures'
import { DataCatalogScene } from '../DataCatalogScene'
import type { UsageSnapshotApi } from '../generated/api.schemas'
import { PARTLY_FAILED_USAGE_SNAPSHOT, USAGE_SNAPSHOT, USAGE_STORY_METRICS } from '../usageStoryFixtures'

function governanceMocks(snapshot: UsageSnapshotApi | null): Mocks {
    const catalog = catalogStoryMocks()
    return {
        ...catalog,
        get: {
            ...catalog.get,
            '/api/projects/:team_id/data_catalog/metrics/': USAGE_STORY_METRICS,
            '/api/projects/:team_id/data_catalog/usage/': snapshot ? [snapshot] : [],
            '/api/projects/:team_id/data_catalog/usage/latest/': snapshot
                ? snapshot
                : () => [404, { detail: 'No usage scan has finished for this project yet.' }],
        },
    }
}

const meta: Meta<typeof DataCatalogScene> = {
    title: 'Products/Data catalog/Governance',
    component: DataCatalogScene,
    decorators: [mswDecorator({}), inMainContent('w-256')],
    parameters: {
        pageUrl: urls.dataCatalog('governance'),
        mockDate: '2026-10-30',
        featureFlags: [
            FEATURE_FLAGS.TODAY_RAIL_NAV,
            FEATURE_FLAGS.DATA_CATALOG_RESTRUCTURE,
            FEATURE_FLAGS.DATA_CATALOG_USAGE,
        ],
        msw: { mocks: governanceMocks(USAGE_SNAPSHOT) },
        testOptions: { snapshotBrowsers: [] },
    },
}

export default meta
type Story = StoryObj<typeof DataCatalogScene>

export const WithScan: Story = {}
export const Narrow: Story = { decorators: [inMainContent('w-128')] }
export const NoScanYet: Story = { parameters: { msw: { mocks: governanceMocks(null) } } }
export const PartlyFailed: Story = { parameters: { msw: { mocks: governanceMocks(PARTLY_FAILED_USAGE_SNAPSHOT) } } }
