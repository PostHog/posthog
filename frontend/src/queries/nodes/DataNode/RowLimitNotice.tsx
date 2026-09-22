import { useValues } from 'kea'

import { IconInfo } from '@posthog/icons'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'

export function rowLimitReachedText(dataLimit: number): string {
    return `Default limit of ${dataLimit} rows reached. Try adding a LIMIT clause to adjust.`
}

/** Tells the reader that the backend cut the result, on surfaces that render the
 *  visualization alone and so never show the table footer. */
export function RowLimitNotice(): JSX.Element | null {
    const { hasMoreData, dataLimit } = useValues(dataNodeLogic)

    if (!hasMoreData || !dataLimit) {
        return null
    }

    return (
        <div className="shrink-0 flex items-center gap-1 border-t bg-surface-primary px-2 py-1 text-xs text-secondary">
            <IconInfo className="shrink-0" />
            <span>{rowLimitReachedText(dataLimit)}</span>
        </div>
    )
}
