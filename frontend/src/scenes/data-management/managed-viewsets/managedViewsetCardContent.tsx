import { IconPiggyBank } from '@posthog/icons'

import { DataWarehouseManagedViewsetKind } from '~/queries/schema/schema-general'

export const VIEWSET_DESCRIPTIONS: Record<
    DataWarehouseManagedViewsetKind,
    { title: string; description: string; docsUrl: string; configUrl: string; icon: JSX.Element }
> = {
    revenue_analytics: {
        title: 'Revenue Analytics',
        description:
            'Track and analyze revenue data from your payment providers and custom events. Automatically creates optimized views for revenue metrics, trends, and customer lifetime value.',
        docsUrl: 'https://posthog.com/docs/revenue-analytics',
        configUrl: '/data-management/revenue',
        icon: <IconPiggyBank className="text-xl" />,
    },
}

export const VIEWSET_TOGGLING_REASON = 'Saving, this might take a few seconds...'

export function viewsetToggleLabel(isToggling: boolean, isEnabled: boolean): string {
    if (isToggling) {
        return isEnabled ? 'Disabling, please wait a moment...' : 'Enabling, please wait a moment...'
    }
    return isEnabled ? 'Enabled' : 'Disabled'
}
