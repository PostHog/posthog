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
import { urls } from 'scenes/urls'
import { VIEW_TYPES, ViewTypeInfo } from 'scenes/views/viewsUtils'
import { ViewTypeIcon } from 'scenes/views/ViewTypeIcon'

/** Points a Products search for a view type to the Views pane, where those types live. */
export function TodayProductsViewsHint({ viewTypes }: { viewTypes: ViewTypeInfo[] }): JSX.Element {
    const title = viewTypes
        .map((info, index) => (index === 0 ? info.pluralLabel : info.pluralLabel.toLowerCase()))
        .join(' and ')
    return (
        <Empty className="mt-2 gap-3 p-4" data-attr="today-products-views-hint">
            <EmptyHeader>
                <IconStack>
                    {VIEW_TYPES.map((info) => (
                        <IconStackItem key={info.type} color={info.color}>
                            <ViewTypeIcon type={info.type} />
                        </IconStackItem>
                    ))}
                </IconStack>
                <EmptyTitle>{`${title} are in Views`}</EmptyTitle>
                <EmptyDescription>Canvases, notebooks and dashboards live in Views.</EmptyDescription>
            </EmptyHeader>
            <EmptyContent>
                <Button
                    size="sm"
                    variant="outline"
                    render={<LinkPrimitive to={urls.views()} />}
                    data-attr="today-products-views-hint-open"
                >
                    Open Views
                </Button>
            </EmptyContent>
        </Empty>
    )
}
