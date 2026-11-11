import type { Meta, StoryObj } from '@storybook/react'
import { waitFor } from '@testing-library/react'
import { combineUrl } from 'kea-router'

import { FEATURE_FLAGS } from 'lib/constants'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'

import { catalogStoryMocks, grantWarehouseEditorAccess, inMainContent } from '../catalogStoryFixtures'
import { DataCatalogScene } from '../DataCatalogScene'

const DATA_QUALITY_URL = urls.dataCatalog('data-quality')

const meta: Meta<typeof DataCatalogScene> = {
    title: 'Products/Data catalog/Data quality',
    component: DataCatalogScene,
    beforeEach: grantWarehouseEditorAccess,
    decorators: [mswDecorator({}), inMainContent('w-256')],
    parameters: {
        pageUrl: DATA_QUALITY_URL,
        mockDate: '2026-09-15',
        featureFlags: [FEATURE_FLAGS.TODAY_RAIL_NAV, FEATURE_FLAGS.DATA_CATALOG_RESTRUCTURE],
        msw: { mocks: catalogStoryMocks() },
        testOptions: { snapshotBrowsers: [] },
    },
}
export default meta

type Story = StoryObj<typeof DataCatalogScene>

async function clickWhenReady(canvasElement: HTMLElement, selector: string): Promise<HTMLElement> {
    const element = await waitFor(() => {
        const found = canvasElement.querySelector<HTMLElement>(selector)
        if (!found || found.getAttribute('aria-disabled') === 'true') {
            throw new Error(`${selector} not ready yet`)
        }
        return found
    })
    element.click()
    return element
}

export const AllTables: Story = {}

export const Narrow: Story = {
    decorators: [inMainContent('w-128')],
}

async function expandRevenueChecks(canvasElement: HTMLElement): Promise<void> {
    await clickWhenReady(canvasElement, 'button[aria-label="Show checks for revenue_by_account"]')
    await waitFor(() => {
        if (!canvasElement.querySelector('[data-attr="data-catalog-quality-add-check"]')) {
            throw new Error('Checks not shown yet')
        }
    })
}

export const TableExpanded: Story = {
    play: async ({ canvasElement }) => expandRevenueChecks(canvasElement),
}

export const TableExpandedNarrow: Story = {
    decorators: [inMainContent('w-128')],
    play: async ({ canvasElement }) => expandRevenueChecks(canvasElement),
}

export const FilteredToTable: Story = {
    parameters: {
        pageUrl: combineUrl(DATA_QUALITY_URL, { table: 'revenue_by_account' }).url,
    },
}

export const FilteredToTableWithoutChecks: Story = {
    parameters: {
        pageUrl: combineUrl(DATA_QUALITY_URL, { table: 'hubspot.contacts' }).url,
    },
}

export const FilteredToMissingTable: Story = {
    parameters: {
        pageUrl: combineUrl(DATA_QUALITY_URL, { table: 'orders_archive' }).url,
    },
}

export const RunningAllChecks: Story = {
    play: async ({ canvasElement }) => {
        const runAll = await clickWhenReady(canvasElement, '[data-attr="data-catalog-quality-run-all"]')
        await waitFor(() => {
            if (runAll.getAttribute('aria-busy') !== 'true') {
                throw new Error('Run not started yet')
            }
        })
    },
}
