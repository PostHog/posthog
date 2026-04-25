import { IconEye } from '@posthog/icons'

import { ErrorTrackingRuntime } from 'lib/components/Errors/types'

import { RuntimeIcon } from 'products/error_tracking/frontend/components/RuntimeIcon'

import { ItemRenderer, TimelineItem } from '..'
import { StandardizedPreview } from './base'
import { LazyEventDetailsRenderer } from './eventDetails'
import { buildOpenInActivityTabMenuItem } from './menuItems'

export interface PageItem extends TimelineItem {
    payload: {
        runtime: ErrorTrackingRuntime
        url: string
    }
}

export const pageRenderer: ItemRenderer<PageItem> = {
    sourceIcon: ({ item }) => <RuntimeIcon runtime={item.payload.runtime} />,
    categoryIcon: <IconEye />,
    render: ({ item }): JSX.Element => {
        return <StandardizedPreview primaryText={getUrlPathname(item.payload.url)} />
    },
    renderExpanded: LazyEventDetailsRenderer,
    getMenuItems: ({ item }) => [
        ...(item.payload.url
            ? [
                  {
                      key: 'open-page-view',
                      label: 'Open page view',
                      onClick: () => window.open(item.payload.url, '_blank', 'noopener,noreferrer'),
                  },
              ]
            : []),
        ...buildOpenInActivityTabMenuItem({ eventId: item.id, timestamp: item.timestamp.toISOString() }),
    ],
}

function getUrlPathname(url: string): string {
    try {
        const parsedUrl = new URL(url)
        return parsedUrl.pathname
    } catch {
        return url
    }
}
