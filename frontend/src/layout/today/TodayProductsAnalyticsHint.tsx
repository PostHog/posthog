import {
    Button,
    Empty,
    EmptyContent,
    EmptyDescription,
    EmptyHeader,
    EmptyTitle,
    IconStack,
    IconStackItem,
} from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { AnalyticsTypeIcon } from 'scenes/analytics/AnalyticsTypeIcon'
import { ANALYTICS_TYPES, AnalyticsTypeInfo } from 'scenes/analytics/analyticsUtils'
import { urls } from 'scenes/urls'

/** Points a Products search for an analytics type to the Analytics pane, where those types live. */
export function TodayProductsAnalyticsHint({ analyticsTypes }: { analyticsTypes: AnalyticsTypeInfo[] }): JSX.Element {
    const title = analyticsTypes
        .map((info, index) => (index === 0 ? info.pluralLabel : info.pluralLabel.toLowerCase()))
        .join(' and ')
    return (
        <Empty className="mt-2 gap-3 p-4" data-attr="today-products-analytics-hint">
            <EmptyHeader>
                <IconStack>
                    {ANALYTICS_TYPES.map((info) => (
                        <IconStackItem key={info.type} color={info.color}>
                            <AnalyticsTypeIcon type={info.type} />
                        </IconStackItem>
                    ))}
                </IconStack>
                <EmptyTitle>{`${title} are in Analytics`}</EmptyTitle>
                <EmptyDescription>Canvases, dashboards, notebooks and insights live in Analytics.</EmptyDescription>
            </EmptyHeader>
            <EmptyContent>
                <Button
                    size="sm"
                    variant="outline"
                    render={<LinkPrimitive to={urls.analyticsList()} />}
                    data-attr="today-products-analytics-hint-open"
                >
                    Open Analytics
                </Button>
            </EmptyContent>
        </Empty>
    )
}
