import { IconStack, IconStackItem } from '@posthog/quill'

export interface TodayChip {
    key: string
    /** Read out for the chip, which shows only an icon. */
    label: string
    color: string
    icon: JSX.Element
    /** Lifted, because the matching item is hovered elsewhere on the page. */
    active?: boolean
    onClick: () => void
    onHoverChange: (hovered: boolean) => void
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
        <IconStack className="TodayChipStack">
            {chips.map((chip) => (
                <IconStackItem
                    key={chip.key}
                    color={chip.color}
                    active={chip.active}
                    render={
                        <button
                            type="button"
                            aria-label={`Open ${chip.label}`}
                            data-attr={dataAttr}
                            onClick={chip.onClick}
                            onMouseEnter={() => chip.onHoverChange(true)}
                            onMouseLeave={() => chip.onHoverChange(false)}
                        />
                    }
                >
                    {chip.icon}
                </IconStackItem>
            ))}
        </IconStack>
    )
}
