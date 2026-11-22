import { useValues } from 'kea'

import { Item, ItemContent, ItemDescription, Skeleton, Text } from '@posthog/quill'

import { UsageScanWindow } from '../components/UsageScanWindow'
import { usageLogic } from '../usageLogic'
import { CatalogSuggestedMetricsTable } from './CatalogSuggestedMetricsTable'

const SKELETON_ROWS = 5

export function CatalogSuggestedMetrics(): JSX.Element {
    const { latest, latestLoadFailed } = useValues(usageLogic)

    if (latestLoadFailed) {
        return (
            <Item variant="outline" tone="destructive">
                <ItemContent>
                    <ItemDescription>
                        Couldn't load the suggested metrics. Refresh the page, and if it keeps happening contact
                        support.
                    </ItemDescription>
                </ItemContent>
            </Item>
        )
    }
    if (latest === null) {
        return (
            <div className="flex flex-col gap-2" aria-busy="true">
                {Array.from({ length: SKELETON_ROWS }, (_, index) => (
                    <Skeleton key={index} className="h-10 w-full" />
                ))}
            </div>
        )
    }

    return (
        <div className="flex flex-col gap-2">
            <div className="flex flex-col gap-1">
                <Text size="xs" variant="muted" render={<p className="m-0" />}>
                    These measures come up often in queries and charts, but no metric defines them yet. Open one to
                    create a metric from its query.
                </Text>
                {latest !== 'none' && <UsageScanWindow scan={latest} />}
            </div>
            <CatalogSuggestedMetricsTable />
        </div>
    )
}
