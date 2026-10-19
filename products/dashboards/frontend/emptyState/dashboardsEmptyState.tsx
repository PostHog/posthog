import * as chartPng from '@posthog/brand/hoggies/png/chart'
import { IconDashboard } from '@posthog/icons'

import { pngHoggie } from 'lib/brand/hoggies'
import type { SceneProductEmptyState } from 'lib/components/ProductEmptyState/types'
import { DashboardsTab } from 'scenes/dashboard/dashboards/dashboardsLogic'
import { Scene } from 'scenes/sceneTypes'

import { ProductKey } from '~/queries/schema/schema-general'

import { DashboardsTabs } from '../DashboardsTabs'
import { DashboardsPreview } from './DashboardsPreview'
import { DashboardsPrimaryAction } from './DashboardsPrimaryAction'
import { dashboardsSetupLogic } from './dashboardsSetupLogic'

const HedgehogChart = pngHoggie(chartPng)

export const dashboardsEmptyState: SceneProductEmptyState = {
    statusLogic: dashboardsSetupLogic,
    scenes: [
        {
            scene: Scene.Dashboards,
            tabs: [undefined, DashboardsTab.All, DashboardsTab.Yours, DashboardsTab.Pinned],
            tabSource: 'search',
        },
    ],
    SceneNav: DashboardsTabs,
    config: {
        productKey: ProductKey.DASHBOARDS,
        productName: 'Dashboards',
        icon: <IconDashboard />,
        accentColor: 'var(--color-product-dashboards-light)',
        accentColorDark: 'var(--color-product-dashboards-dark)',
        hedgehog: HedgehogChart,
        text: {
            'needs-setup': {
                headline: 'Put the numbers you check every day on one page',
                lead: 'A dashboard collects insights, replays, and anything else you track into a single view your whole team can open. Start from a template built for a common job, like product health or web traffic, or start blank and add tiles as you go.',
            },
        },
        PrimaryAction: DashboardsPrimaryAction,
        skippable: false,
        docsUrl: 'https://posthog.com/docs/product-analytics/dashboards',
        previewLabel: 'Your dashboard, once created',
        Preview: DashboardsPreview,
    },
}
