import { formatAbsoluteTime, formatRelativeTime } from './warehouseConsoleFormat'

/** A relative time that shows the exact time on hover. */
export function WarehouseTime({ iso }: { iso: string | null | undefined }): JSX.Element {
    return (
        <time dateTime={iso ?? undefined} title={formatAbsoluteTime(iso)} className="whitespace-nowrap">
            {formatRelativeTime(iso)}
        </time>
    )
}
