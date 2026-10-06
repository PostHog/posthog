export interface TodayChip {
    key: string
    /** Read out for the chip, which shows only an icon. */
    label: string
    color: string
    icon: JSX.Element
    /** Lifted, because the matching item is hovered elsewhere on the page. */
    active?: boolean
    onClick?: () => void
    onHoverChange?: (hovered: boolean) => void
}

interface TodayChipStackProps {
    chips: TodayChip[]
    dataAttr: string
}

export function TodayChipStack({ chips, dataAttr }: TodayChipStackProps): JSX.Element | null {
    if (chips.length === 0) {
        return null
    }
    return (
        <span className="TodayChipStack">
            {chips.map((chip, index) => (
                <button
                    key={chip.key}
                    type="button"
                    className="TodayChipStack__chip"
                    aria-label={`Open ${chip.label}`}
                    data-active={chip.active ?? false}
                    data-attr={dataAttr}
                    // eslint-disable-next-line react/forbid-dom-props
                    style={
                        {
                            '--index': index,
                            '--tilt': index % 2 === 0 ? '-3deg' : '3deg',
                            '--report-color': chip.color,
                        } as React.CSSProperties
                    }
                    onClick={chip.onClick}
                    onMouseEnter={() => chip.onHoverChange?.(true)}
                    onMouseLeave={() => chip.onHoverChange?.(false)}
                >
                    {chip.icon}
                </button>
            ))}
        </span>
    )
}
