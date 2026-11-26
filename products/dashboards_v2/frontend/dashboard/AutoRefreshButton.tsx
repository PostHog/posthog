import { IconRefresh } from '@posthog/icons'
import {
    Button,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuGroup,
    DropdownMenuItem,
    DropdownMenuLabel,
    DropdownMenuRadioGroup,
    DropdownMenuRadioItem,
    DropdownMenuSeparator,
    DropdownMenuTrigger,
} from '@posthog/quill'

export const DEFAULT_REFRESH_INTERVALS = [60, 300, 900, 1800, 3600]

const OFF = 'off'

export function intervalLabel(seconds: number): string {
    if (seconds % 3600 === 0) {
        const hours = seconds / 3600
        return hours === 1 ? '1 hour' : `${hours} hours`
    }
    if (seconds % 60 === 0) {
        const minutes = seconds / 60
        return minutes === 1 ? '1 minute' : `${minutes} minutes`
    }
    return `${seconds} seconds`
}

export interface AutoRefreshProps {
    intervals?: number[]
    interval: number | null
    onIntervalChange: (interval: number | null) => void
    onRefresh: () => void
    refreshing?: boolean
}

export function AutoRefreshButton({
    intervals = DEFAULT_REFRESH_INTERVALS,
    interval,
    onIntervalChange,
    onRefresh,
    refreshing = false,
}: AutoRefreshProps): JSX.Element {
    const label = interval ? `Refresh every ${intervalLabel(interval)}` : 'Refresh'
    return (
        <DropdownMenu>
            <DropdownMenuTrigger
                render={
                    <Button size="sm" tooltip={label} aria-label={label} data-attr="dashboard-v2-refresh">
                        <IconRefresh className={refreshing ? 'animate-spin' : undefined} />
                        {interval ? intervalLabel(interval) : 'Refresh'}
                    </Button>
                }
            />
            <DropdownMenuContent align="end">
                <DropdownMenuGroup>
                    <DropdownMenuItem data-attr="dashboard-v2-refresh-now" disabled={refreshing} onClick={onRefresh}>
                        Refresh now
                    </DropdownMenuItem>
                </DropdownMenuGroup>
                <DropdownMenuSeparator />
                <DropdownMenuGroup>
                    <DropdownMenuLabel>Auto refresh every</DropdownMenuLabel>
                    <DropdownMenuRadioGroup
                        value={interval === null ? OFF : String(interval)}
                        onValueChange={(value) => onIntervalChange(value === OFF ? null : Number(value))}
                    >
                        <DropdownMenuRadioItem value={OFF} data-attr="dashboard-v2-refresh-interval">
                            Off
                        </DropdownMenuRadioItem>
                        {intervals.map((seconds) => (
                            <DropdownMenuRadioItem
                                key={seconds}
                                value={String(seconds)}
                                data-attr="dashboard-v2-refresh-interval"
                            >
                                {intervalLabel(seconds)}
                            </DropdownMenuRadioItem>
                        ))}
                    </DropdownMenuRadioGroup>
                </DropdownMenuGroup>
            </DropdownMenuContent>
        </DropdownMenu>
    )
}
