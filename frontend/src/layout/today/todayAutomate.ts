import type { FeatureFlagsSet } from 'lib/logic/featureFlagLogic'
import { urls } from 'scenes/urls'

import { getNavProductPages } from '~/layout/panel-layout/navbar/tabs/navProductItems'
import { FileSystemIconType, FileSystemImport } from '~/queries/schema/schema-general'

import {
    TodayPaneProduct,
    TodayPaneProductSpec,
    paneProductForPath,
    paneProductsFor,
    shownPaneProducts,
} from './todayPaneProducts'

function automateSpecs(): TodayPaneProductSpec[] {
    return [
        { href: urls.workflows() },
        { href: urls.transactional() },
        // Batch export pages live under /pipeline and open from the Batch exports tab of Destinations.
        { href: urls.destinations(), section: '/pipeline/batch-exports' },
        { href: urls.subscriptions() },
        { href: urls.inbox('scouts') },
    ]
}

/**
 * Subscriptions and Scouts have no page of their own in the product list, so Automate adds one for each. Scouts copies
 * the Self-driving page, so it keeps that page's flag.
 */
function automatePages(): FileSystemImport[] {
    const pages = getNavProductPages()
    const inbox = pages.find((page) => page.href === urls.inbox())
    return [
        ...pages,
        {
            path: 'Subscriptions',
            iconType: 'subscriptions' as FileSystemIconType,
            href: urls.subscriptions(),
        },
        ...(inbox ? [{ ...inbox, path: 'Scouts', displayLabel: 'Scouts', href: urls.inbox('scouts') }] : []),
    ]
}

export function automateProducts(): TodayPaneProduct[] {
    return paneProductsFor(automatePages(), automateSpecs())
}

export function automateItems(featureFlags: FeatureFlagsSet): TodayPaneProduct[] {
    return shownPaneProducts(automateProducts(), featureFlags)
}

/** Matches against every Automate product, shown or not, so a page keeps its pane while a flag hides its row. */
export function automateProductForPath(path: string): TodayPaneProduct | undefined {
    return paneProductForPath(automateProducts(), path)
}
