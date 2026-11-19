import { IconRefresh } from '@posthog/icons'
import { Button } from '@posthog/quill'

import { dayjs, type Dayjs } from 'lib/dayjs'

export function QuillCardMetaRefreshButton({
    onRefresh,
    lastRefresh,
    disabledReason,
    dataAttr,
}: {
    onRefresh: () => void
    lastRefresh?: string | number | Dayjs | null
    disabledReason?: string
    dataAttr: string
}): JSX.Element {
    const label = lastRefresh ? `Refresh data (last computed ${dayjs(lastRefresh).fromNow()})` : 'Refresh data'
    return (
        <Button
            className="CardMeta__refresh"
            size="icon"
            onClick={onRefresh}
            disabledReason={disabledReason}
            tooltip={disabledReason ? undefined : label}
            aria-label="Refresh data"
            data-attr={dataAttr}
        >
            <IconRefresh />
        </Button>
    )
}
