import api from 'lib/api'
import { FEATURE_FLAGS } from 'lib/constants'
import { urls } from 'scenes/urls'

import { splitPath } from '~/layout/panel-layout/ProjectTree/utils'
import { FileSystemEntry, FileSystemIconType } from '~/queries/schema/schema-general'

import { TODAY_AUTOMATE_RECENT_TYPES, TodayAutomateRecent } from './todayAutomateRecents'
import type { TodayPaneProductSpec, TodayProductPaneConfig } from './todayPaneProducts'
import { TODAY_RECENTS_LIMIT } from './todayRecents'

function automateSpecs(): TodayPaneProductSpec[] {
    return [
        { href: urls.workflows() },
        { href: urls.transactional() },
        // Batch export pages live under /pipeline and open from the Batch exports tab of Destinations.
        { href: urls.destinations(), section: '/pipeline/batch-exports', iconType: 'data_pipeline' },
        {
            href: urls.subscriptions(),
            item: { path: 'Subscriptions', iconType: 'team_activity', href: urls.subscriptions() },
            // pinned: autocapture `data-attr` suffix, `automate-sidebar-product-subscriptions`.
            key: 'subscriptions',
        },
        {
            href: urls.inbox('scouts'),
            // A tab of Self-driving, so it carries that product's flag and scene.
            item: {
                path: 'Scouts',
                iconType: 'inbox' as FileSystemIconType,
                href: urls.inbox('scouts'),
                flag: FEATURE_FLAGS.PRODUCT_AUTONOMY,
                sceneKey: 'Inbox',
            },
        },
    ]
}

/** Destinations viewed before, from the server's view history. Workflows and subscriptions record no server views. */
export function destinationRecentsFromViews(entries: FileSystemEntry[]): TodayAutomateRecent[] {
    return entries.flatMap((entry): TodayAutomateRecent[] =>
        entry.ref && entry.last_viewed_at
            ? [
                  {
                      type: 'hog_function/destination',
                      name: splitPath(entry.path).at(-1) ?? entry.path,
                      href: urls.hogFunction(entry.ref),
                  },
              ]
            : []
    )
}

async function loadViewedDestinations(): Promise<TodayAutomateRecent[]> {
    const response = await api.fileSystem.list({
        type: 'hog_function/destination',
        orderBy: '-last_viewed_at',
        limit: TODAY_RECENTS_LIMIT,
    })
    return destinationRecentsFromViews(response.results)
}

export const AUTOMATE_PANE: TodayProductPaneConfig = {
    pane: 'automate',
    label: 'Automate',
    lead: { id: 'products', rowDataAttr: 'automate-sidebar-product', specs: automateSpecs },
    sections: [],
    recentTypes: TODAY_AUTOMATE_RECENT_TYPES,
    recentTypeInfo: {
        workflow: {
            iconType: 'workflows',
            label: 'Workflow',
            description: 'A workflow. Open it to see its steps, runs, and metrics.',
        },
        'hog_function/destination': {
            iconType: 'data_pipeline',
            label: 'Destination',
            description: 'A destination. Open it to see its configuration and the events it sent.',
        },
        subscription: {
            iconType: 'team_activity',
            label: 'Subscription',
            description: 'A subscription. Open it to see its schedule and delivery history.',
        },
        scout: {
            iconType: 'inbox',
            label: 'Scout',
            description: 'A scout. Open it to see its runs, reports, and what it has learned.',
        },
    },
    loadRecentHistory: loadViewedDestinations,
}
