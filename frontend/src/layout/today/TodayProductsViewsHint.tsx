import { IconGridMasonry } from '@posthog/icons'
import { Button, Empty, EmptyContent, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'
import { ViewTypeInfo } from 'scenes/views/viewsUtils'

/** Points a Products search for dashboards or notebooks to the Views pane, where those types live. */
export function TodayProductsViewsHint({ viewTypes }: { viewTypes: ViewTypeInfo[] }): JSX.Element {
    const title = viewTypes
        .map((info, index) => (index === 0 ? info.pluralLabel : info.pluralLabel.toLowerCase()))
        .join(' and ')
    return (
        <Empty className="mt-2 gap-3 p-4" data-attr="today-products-views-hint">
            <EmptyHeader>
                <EmptyMedia variant="icon">
                    <IconGridMasonry />
                </EmptyMedia>
                <EmptyTitle>{`${title} are in Views`}</EmptyTitle>
                <EmptyDescription>
                    Dashboards and notebooks show your data, so they live in Views with your canvases.
                </EmptyDescription>
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
