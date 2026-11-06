import * as lifeguardPng from '@posthog/brand/hoggies/png/lifeguard'
import { IconBell } from '@posthog/icons'

import { pngHoggie } from 'lib/brand/hoggies'
import type { SceneProductEmptyState } from 'lib/components/ProductEmptyState/types'

import { ProductKey } from '~/queries/schema/schema-general'

import { AlertsPreview } from './AlertsPreview'
import { AlertsPrimaryAction } from './AlertsPrimaryAction'
import { alertsSetupLogic } from './alertsSetupLogic'

const HedgehogLifeguard = pngHoggie(lifeguardPng)

export const alertsEmptyState: SceneProductEmptyState = {
    statusLogic: alertsSetupLogic,
    config: {
        productKey: ProductKey.ALERTS,
        productName: 'Alerts',
        icon: <IconBell />,
        accentColor: 'var(--color-product-alerts-light)',
        accentColorDark: 'var(--color-product-alerts-dark)',
        hedgehog: HedgehogLifeguard,
        text: {
            'needs-setup': {
                headline: 'Find out a metric moved without watching the dashboard',
                lead: 'An alert re-runs one insight or log search on a schedule and compares the result to a threshold you set. When the value crosses it, PostHog notifies you in Slack, Microsoft Teams, email, or a webhook, and keeps a record of every check it ran.',
                hint: 'Insight alerts start on the insight. Open one, then pick Alerts in its actions sidebar.',
            },
        },
        PrimaryAction: AlertsPrimaryAction,
        docsUrl: 'https://posthog.com/docs/alerts',
        previewLabel: 'An alert, once set',
        Preview: AlertsPreview,
    },
}
