import { IconChevronDown, IconPlay } from '@posthog/icons'
import { LemonButton, LemonMenuItems, LemonMenuOverlay } from '@posthog/lemon-ui'

export type DuckSqlRunMode = 'auto' | 'cell_upstream' | 'cell' | 'cell_downstream'

type DuckSqlRunMenuProps = {
    isFresh: boolean
    isStale: boolean
    loading: boolean
    queued: boolean
    disabledReason?: string
    onRun: (mode: DuckSqlRunMode) => void
}

export const DuckSqlRunMenu = ({
    isFresh,
    isStale,
    loading,
    queued,
    disabledReason,
    onRun,
}: DuckSqlRunMenuProps): JSX.Element => {
    const duckSqlRunIconClass = isFresh ? 'text-success' : isStale ? 'text-danger' : undefined
    const duckSqlRunTooltip = `Run SQL (duckdb) query.${queued ? ' Queued.' : isStale ? ' Stale.' : ''}`

    const duckSqlRunMenuItems: LemonMenuItems = [
        {
            label: 'Run (auto)',
            onClick: () => onRun('auto'),
        },
        {
            label: 'Run cell + upstream',
            onClick: () => onRun('cell_upstream'),
        },
        {
            label: 'Run cell',
            onClick: () => onRun('cell'),
        },
        {
            label: 'Run cell + downstream',
            onClick: () => onRun('cell_downstream'),
        },
    ]

    return (
        <LemonButton
            onClick={() => onRun('auto')}
            size="small"
            icon={<IconPlay className={duckSqlRunIconClass} />}
            loading={loading || queued}
            disabledReason={disabledReason}
            tooltip={duckSqlRunTooltip}
            sideAction={{
                icon: <IconChevronDown />,
                dropdown: {
                    placement: 'bottom-end',
                    overlay: <LemonMenuOverlay items={duckSqlRunMenuItems} />,
                },
                divider: false,
                'aria-label': 'Open run options',
                disabledReason: disabledReason,
            }}
        />
    )
}
