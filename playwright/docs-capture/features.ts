import { Page, expect } from '@playwright/test'

import { urls } from 'scenes/urls'

export type ShotFn = (page: Page) => Promise<void>

export interface FeatureCapture {
    /** Stable kebab-case slug. Must match `data-feature` value(s) in the frontend. */
    slug: string
    /** Path on posthog.com/website where the resulting screenshots are referenced. */
    docsPath: string
    /** Run once before any shots — navigate, log in to a particular project, etc. */
    setup: ShotFn
    /**
     * Named shots, taken in declaration order. Each fn mutates UI state to the desired pose
     * (open a panel, type into a search box, hover an element). The runner then takes a
     * screenshot scoped to `[data-feature="<slug>"]`.
     */
    shots: Record<string, ShotFn>
}

const noop: ShotFn = async () => {}

export const features: FeatureCapture[] = [
    {
        slug: 'dashboards',
        docsPath: '/docs/product-analytics/dashboards',
        setup: async (page) => {
            await page.goto(urls.dashboards())
            const firstRow = page.locator('table [data-attr="dashboard-name"]').first()
            await expect(firstRow).toBeVisible()
            await firstRow.click()
            await expect(page.locator('[data-feature="dashboards"]')).toBeVisible()
        },
        shots: {
            default: noop,
        },
    },
    {
        slug: 'taxonomic-filter',
        docsPath: '/docs/product-analytics/taxonomic-filter',
        setup: async (page) => {
            await page.goto(urls.insightNew())
            await page.getByTestId('insight-filters-add-filter-group').first().click()
            await expect(page.locator('[data-feature="taxonomic-filter"]')).toBeVisible()
        },
        shots: {
            default: noop,
            search: async (page) => {
                await page.getByTestId('taxonomic-filter-searchfield').fill('browser')
                await page.waitForTimeout(300)
            },
        },
    },
]
