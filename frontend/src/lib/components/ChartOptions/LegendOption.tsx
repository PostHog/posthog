import { ChartOptionSelect } from './ChartOptionSelect'
import { ChartOptionSwitch } from './ChartOptionSwitch'

export type LegendPosition = 'top' | 'bottom' | 'left' | 'right'

const POSITION_OPTIONS: { value: LegendPosition; label: string }[] = [
    { value: 'top', label: 'Top' },
    { value: 'bottom', label: 'Bottom' },
    { value: 'left', label: 'Left' },
    { value: 'right', label: 'Right' },
]

export interface LegendOptionProps {
    showLegend: boolean
    onShowLegendChange: (showLegend: boolean) => void
    /** Leave out on charts that draw the legend in a fixed place. */
    position?: LegendPosition
    onPositionChange?: (position: LegendPosition) => void
}

export function LegendOption({
    showLegend,
    onShowLegendChange,
    position,
    onPositionChange,
}: LegendOptionProps): JSX.Element {
    return (
        <div className="flex flex-col gap-2">
            <ChartOptionSwitch label="Show legend" checked={showLegend} onChange={onShowLegendChange} />
            {position && onPositionChange && (
                <ChartOptionSelect
                    label="Legend position"
                    value={position}
                    options={POSITION_OPTIONS}
                    onChange={onPositionChange}
                    disabledReason={showLegend ? undefined : 'Turn the legend on to set its position'}
                />
            )}
        </div>
    )
}
