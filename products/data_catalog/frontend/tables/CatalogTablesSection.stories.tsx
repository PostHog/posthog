import type { Meta, StoryObj } from '@storybook/react'
import { waitFor } from '@testing-library/react'
import { combineUrl } from 'kea-router'

import { FEATURE_FLAGS } from 'lib/constants'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'

import { catalogStoryMocks, grantWarehouseEditorAccess, inMainContent } from '../catalogStoryFixtures'
import { DataCatalogScene } from '../DataCatalogScene'

const meta: Meta<typeof DataCatalogScene> = {
    title: 'Products/Data catalog/Tables and views',
    component: DataCatalogScene,
    beforeEach: grantWarehouseEditorAccess,
    decorators: [mswDecorator({}), inMainContent('w-256')],
    parameters: {
        pageUrl: urls.dataCatalog('tables'),
        mockDate: '2026-09-15',
        featureFlags: [FEATURE_FLAGS.TODAY_RAIL_NAV, FEATURE_FLAGS.DATA_CATALOG_RESTRUCTURE],
        msw: { mocks: catalogStoryMocks() },
        testOptions: { snapshotBrowsers: [] },
    },
}
export default meta

type Story = StoryObj<typeof DataCatalogScene>

export const AllTables: Story = {}

export const Narrow: Story = {
    decorators: [inMainContent('w-128')],
}

export const ProposedCertifications: Story = {
    parameters: {
        pageUrl: combineUrl(urls.dataCatalog('tables'), { filter: 'proposed' }).url,
    },
}

export const LoadError: Story = {
    parameters: { msw: { mocks: catalogStoryMocks({ databaseFails: true }) } },
}

export const CertificationsLoadError: Story = {
    parameters: { msw: { mocks: catalogStoryMocks({ certificationsFail: true }) } },
}

async function selectRows(canvasElement: HTMLElement, names: string[]): Promise<void> {
    for (const name of names) {
        const checkbox = await waitFor(() => {
            const element = canvasElement.querySelector<HTMLElement>(`[aria-label="Select ${name}"]`)
            if (!element) {
                throw new Error('Row not rendered yet')
            }
            return element
        })
        checkbox.click()
    }
    await waitFor(() => {
        if (!canvasElement.querySelector('[data-attr="data-catalog-tables-bulk-bar"]')) {
            throw new Error('Bulk bar not shown yet')
        }
    })
}

export const RowsSelected: Story = {
    play: async ({ canvasElement }) => selectRows(canvasElement, ['orders_daily', 'marketing_spend', 'events']),
}

export const NarrowRowsSelected: Story = {
    decorators: [inMainContent('w-128')],
    play: RowsSelected.play,
}
