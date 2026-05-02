import { IconGraph } from '@posthog/icons'

import { ErrorTrackingRuntime } from 'lib/components/Errors/types'

import { RuntimeIcon } from 'products/error_tracking/frontend/components/RuntimeIcon'

import { ItemRenderer, TimelineItem } from '..'
import { StandardizedPreview } from './base'
import { LazyEventDetailsRenderer } from './eventDetails'
import { buildOpenInActivityTabMenuItem } from './menuItems'

export interface CustomItem extends TimelineItem {
    payload: {
        name: string
        runtime: ErrorTrackingRuntime
    }
}

export const customItemRenderer: ItemRenderer<CustomItem> = {
    sourceIcon: ({ item }) => <RuntimeIcon runtime={item.payload.runtime} />,
    categoryIcon: <IconGraph />,
    render: ({ item }): JSX.Element => {
        return <StandardizedPreview primaryText={item.payload.name} />
    },
    renderExpanded: LazyEventDetailsRenderer,
    getMenuItems: ({ item }) =>
        buildOpenInActivityTabMenuItem({
            eventId: item.id,
            timestamp: item.timestamp.toISOString(),
        }),
}
