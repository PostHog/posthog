import { TZLabel } from 'lib/components/TZLabel'
import { dayjs, type Dayjs } from 'lib/dayjs'
import { LemonButton } from 'lib/lemon-ui/LemonButton'

export function DashboardTileRefreshDataButton({
    onRefresh,
    disabledReason,
    lastRefresh,
}: {
    onRefresh: () => void
    disabledReason?: string | null
    lastRefresh?: string | number | Dayjs | null
}): JSX.Element {
    const lastRefreshTime = lastRefresh != null ? dayjs(lastRefresh) : null

    return (
        <LemonButton
            onClick={onRefresh}
            disabledReason={disabledReason}
            fullWidth
            data-attr="dashboard-tile-refresh-data"
        >
            {lastRefreshTime ? (
                <div className="block my-1">
                    Refresh data
                    <p className="text-xs text-muted mt-0.5">
                        Last computed{' '}
                        <TZLabel time={lastRefreshTime} noStyles className="whitespace-nowrap border-dotted border-b" />
                    </p>
                </div>
            ) : (
                <>Refresh data</>
            )}
        </LemonButton>
    )
}
