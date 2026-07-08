import { IconRefresh } from '@posthog/icons'

import { dayjs, type Dayjs } from 'lib/dayjs'
import { LemonButton } from 'lib/lemon-ui/LemonButton'

/** Hover-revealed refresh icon for a card header. Pass to `CardMeta`'s `refreshControl`; the
 * `.CardMeta__refresh` class is the hook `CardMeta.scss` uses to hide it until the tile is hovered.
 * Callers decide whether to render it at all (gating differs per card type). */
export function CardMetaRefreshButton({
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
    return (
        <LemonButton
            className="CardMeta__refresh"
            icon={<IconRefresh />}
            size="small"
            onClick={onRefresh}
            disabledReason={disabledReason}
            tooltip={
                disabledReason
                    ? undefined
                    : lastRefresh
                      ? `Refresh data (last computed ${dayjs(lastRefresh).fromNow()})`
                      : 'Refresh data'
            }
            data-attr={dataAttr}
        />
    )
}
