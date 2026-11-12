import type { Meta, StoryObj } from '@storybook/react'
import { fireEvent, waitFor } from '@testing-library/react'

import { FEATURE_FLAGS } from 'lib/constants'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'
import type { Mocks } from '~/mocks/utils'

import type {
    WarehouseSuggestionApi,
    WarehouseSuggestionStatusApi,
} from 'products/warehouse_suggestions/frontend/generated/api.schemas'

import { catalogStoryMocks, grantWarehouseEditorAccess, inMainContent } from '../catalogStoryFixtures'
import { DataCatalogScene } from '../DataCatalogScene'

const ACTIVE_STATUS: WarehouseSuggestionStatusApi = {
    enabled: true,
    eligible: true,
    days_with_data: 30,
    window_days: 30,
    paused_reason: null,
    refreshed_at: '2026-09-15T08:30:00Z',
    waiting: 0,
    can_show_more: false,
}

function suggestion(
    id: string,
    kind: WarehouseSuggestionApi['kind'],
    name: string,
    payload: Partial<WarehouseSuggestionApi['payload']> = {}
): WarehouseSuggestionApi {
    const read = kind !== 'deprecate'
    return {
        id,
        kind,
        subject_kind: kind === 'certify' ? 'table' : 'saved_query',
        subject_id: `subject-${id}`,
        payload: { subject_name: name, ...payload } as WarehouseSuggestionApi['payload'],
        payload_version: 1,
        evidence: {
            human_requests: read ? 214 : 0,
            human_users: read ? 6 : 0,
            human_days: read ? 27 : 0,
            requests_by_surface: read ? { sql_editor: 150, dashboard: 64 } : {},
            days_with_data: 30,
        },
        evidence_window_start: '2026-08-16T00:00:00Z',
        evidence_window_end: '2026-09-15T00:00:00Z',
        last_seen_at: '2026-09-15T08:30:00Z',
        status: 'proposed',
        surfaced_at: '2026-09-15T08:30:00Z',
        reviewed_by: null,
        reviewed_at: null,
        dismissal_reason: null,
        dismissal_note: null,
        created_asset: null,
        asset_outcome: null,
        realized_seconds_saved_per_month: null,
        realized_bytes_saved_per_month: null,
        can_act: true,
        assignee: null,
    }
}

const MIXED_SUGGESTIONS = [
    suggestion('1', 'materialize', 'orders_daily', {
        refresh_interval_seconds: 86400,
        saves_seconds_per_month: 5400,
        saves_bytes_per_month: 3 * 10 ** 12,
        waiting_seconds_saved_per_month: 5400,
        background_seconds_saved_per_month: 0,
        main_saving: 'waiting',
        read_seconds: 12,
        freshness_today_seconds: 3600,
        freshness_after_seconds: 90000,
        live_sources: { names: ['events'], hidden_count: 0 },
        unknown_sources: { names: [], hidden_count: 0 },
        refresh_interval_basis: 'source_sync',
        refresh_mode: 'full',
    }),
    suggestion('2', 'certify', 'stripe_charges'),
    suggestion('3', 'deprecate', 'old_marketing_rollup', {
        materialized: true,
        refresh_seconds_per_month: 2700,
        refresh_bytes_per_month: 2 * 10 ** 12,
    }),
]

function suggestionsMocks(results: WarehouseSuggestionApi[], status: WarehouseSuggestionStatusApi): Mocks {
    const catalog = catalogStoryMocks()
    return {
        ...catalog,
        get: {
            ...catalog.get,
            '/api/projects/:team_id/warehouse_suggestions/': { count: results.length, results },
            '/api/projects/:team_id/warehouse_suggestions/status/': status,
        },
    }
}

const meta: Meta<typeof DataCatalogScene> = {
    title: 'Products/Data catalog/Suggestions',
    component: DataCatalogScene,
    beforeEach: grantWarehouseEditorAccess,
    decorators: [mswDecorator({}), inMainContent('w-256')],
    parameters: {
        pageUrl: urls.dataCatalog('suggestions'),
        mockDate: '2026-09-15T10:30:00Z',
        featureFlags: [
            FEATURE_FLAGS.TODAY_RAIL_NAV,
            FEATURE_FLAGS.DATA_CATALOG_RESTRUCTURE,
            FEATURE_FLAGS.WAREHOUSE_SUGGESTIONS,
        ],
        msw: { mocks: suggestionsMocks(MIXED_SUGGESTIONS, ACTIVE_STATUS) },
        testOptions: { snapshotBrowsers: [] },
    },
}
export default meta

type Story = StoryObj<typeof DataCatalogScene>

export const EveryKind: Story = {}

export const AllCaughtUpWithMoreWaiting: Story = {
    parameters: {
        msw: { mocks: suggestionsMocks([], { ...ACTIVE_STATUS, waiting: 4, can_show_more: true }) },
    },
}

export const AllCaughtUp: Story = {
    parameters: {
        msw: { mocks: suggestionsMocks([], ACTIVE_STATUS) },
    },
}

async function waitForElement<T extends Element>(root: ParentNode, selector: string): Promise<T> {
    return await waitFor(() => {
        const element = root.querySelector<T>(selector)
        if (!element) {
            throw new Error(`${selector} not rendered yet`)
        }
        return element
    })
}

export const FilteredByName: Story = {
    play: async ({ canvasElement }) => {
        const search = await waitForElement<HTMLInputElement>(
            canvasElement,
            '[data-attr="data-catalog-suggestions-search"]'
        )
        fireEvent.change(search, { target: { value: 'stripe' } })
    },
}

export const BulkApproveDialog: Story = {
    play: async ({ canvasElement }) => {
        await waitForElement(canvasElement, '[aria-label^="Select every"]')
        canvasElement
            .querySelectorAll<HTMLElement>('[aria-label^="Select every"]')
            .forEach((checkbox) => checkbox.click())
        const approve = await waitForElement<HTMLElement>(
            canvasElement,
            '[data-attr="data-catalog-suggestions-bulk-accept"]'
        )
        approve.click()
        await waitForElement(document, '[data-attr="warehouse-suggestions-bulk-accept-dialog"]')
    },
}
