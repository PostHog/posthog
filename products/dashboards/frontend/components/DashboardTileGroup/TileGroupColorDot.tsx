import clsx from 'clsx'

import type { DashboardTileGroupColorEnumApi } from '../../generated/api.schemas'

const DOT_CLASS_NAMES: Record<DashboardTileGroupColorEnumApi, string> = {
    blue: 'bg-[var(--blue)]',
    purple: 'bg-[var(--purple)]',
    green: 'bg-[var(--green)]',
    yellow: 'bg-[var(--warning)]',
    orange: 'bg-[var(--color-orange-500)]',
    red: 'bg-[var(--danger)]',
}

export function TileGroupColorDot({
    color,
    className,
}: {
    color: DashboardTileGroupColorEnumApi
    className?: string
}): JSX.Element {
    return <span aria-hidden className={clsx('inline-block size-2 rounded-full', DOT_CLASS_NAMES[color], className)} />
}
