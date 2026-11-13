import type { Meta, StoryObj } from '@storybook/react'

import { useStorybookMocks } from '~/mocks/browser'

import { CatalogSetupBanner } from './CatalogSetupBanner'

const SMALL_CATALOG = ['weekly_active_users', 'signups', 'checkout_conversion'].map((name, index) => ({
    id: `metric-${index}`,
    name,
    status: 'proposed',
}))

const meta: Meta<typeof CatalogSetupBanner> = {
    title: 'Data catalog/Catalog setup banner',
    component: CatalogSetupBanner,
    parameters: {
        viewMode: 'story',
        // Used on one scene only, with no layout a regression broke before, so it renders without a baseline.
        testOptions: { snapshotBrowsers: [] },
    },
    render: () => {
        useStorybookMocks({
            get: {
                '/api/projects/:team_id/data_catalog/metrics/': {
                    count: SMALL_CATALOG.length,
                    next: null,
                    results: SMALL_CATALOG,
                },
            },
        })
        return (
            <div className="@container w-240 p-4">
                <CatalogSetupBanner />
            </div>
        )
    },
}
export default meta

export const SmallCatalog: StoryObj<typeof CatalogSetupBanner> = {}
