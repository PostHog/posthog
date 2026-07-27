import { Tooltip } from 'lib/lemon-ui/Tooltip'

export function CardTopHeadingRow({
    typeLabel,
    typeTitle,
    showTypeLabel = true,
    dateText,
    dateTooltip,
    children,
}: {
    typeLabel?: string | null
    typeTitle?: string
    showTypeLabel?: boolean
    dateText?: string | null
    dateTooltip?: string | null
    children?: React.ReactNode
}): JSX.Element {
    return (
        <div className="flex items-center gap-1">
            {showTypeLabel && typeLabel ? <span title={typeTitle ?? typeLabel}>{typeLabel}</span> : null}
            {dateText ? (
                <>
                    {showTypeLabel && typeLabel ? <span>•</span> : null}
                    {dateTooltip ? (
                        <Tooltip title={dateTooltip}>
                            <span className="whitespace-nowrap">{dateText}</span>
                        </Tooltip>
                    ) : (
                        <span className="whitespace-nowrap">{dateText}</span>
                    )}
                </>
            ) : null}
            {children}
        </div>
    )
}
