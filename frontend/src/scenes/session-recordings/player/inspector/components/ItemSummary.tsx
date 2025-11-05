import clsx from 'clsx'

import { IconCursor, IconKeyboard, IconWarning } from '@posthog/icons'
import { Tooltip } from '@posthog/lemon-ui'

import { pluralize } from 'lib/utils'

import { InspectorListItemSummary } from '../playerInspectorLogic'

export function ItemSummary({ item }: { item: InspectorListItemSummary }): JSX.Element {
    return (
        <div
            data-attr="item-summary-item"
            className="font-light text-xs w-full flex items-center justify-end gap-2 py-1"
        >
            <div className="flex items-center justify-end">
                <IconCursor className="mr-1" />
                <span>{pluralize(item.clickCount || 0, 'click')}</span>
            </div>
            <div className="flex items-center justify-end">
                <IconKeyboard className="mr-1" />
                <span>{pluralize(item.keypressCount || 0, 'keystroke')}</span>
            </div>
            <div
                className={clsx(
                    'flex text-danger items-center justify-end',
                    (item.errorCount || 0) > 0 ? 'text-danger' : 'text-success'
                )}
            >
                <Tooltip
                    title={`A count of $exception events in this recording. Captured by PostHog's error tracking.`}
                >
                    <IconWarning className="mr-1" />
                    <span>{pluralize(item.errorCount || 0, 'error')}</span>
                </Tooltip>
            </div>
        </div>
    )
}
