import clsx from 'clsx'

import { getSeriesColorPalette } from 'lib/colors'
import { LemonColorPicker } from 'lib/lemon-ui/LemonColor'

const PRESET_COLORS = getSeriesColorPalette()

export interface MetricDirectionColorPickersProps {
    increaseColor: string
    decreaseColor: string
    onIncrease: (color: string) => void
    onDecrease: (color: string) => void
    className?: string
    rowClassName?: string
}

export function MetricDirectionColorPickers({
    increaseColor,
    decreaseColor,
    onIncrease,
    onDecrease,
    className,
    rowClassName,
}: MetricDirectionColorPickersProps): JSX.Element {
    return (
        <div className={clsx('flex flex-col', className)}>
            <div className={clsx('flex items-center justify-between gap-2', rowClassName)}>
                <span className="font-normal">Increase</span>
                <LemonColorPicker
                    colors={PRESET_COLORS}
                    selectedColor={increaseColor}
                    onSelectColor={onIncrease}
                    showCustomColor
                    preventPopoverClose
                />
            </div>
            <div className={clsx('flex items-center justify-between gap-2', rowClassName)}>
                <span className="font-normal">Decrease</span>
                <LemonColorPicker
                    colors={PRESET_COLORS}
                    selectedColor={decreaseColor}
                    onSelectColor={onDecrease}
                    showCustomColor
                    preventPopoverClose
                />
            </div>
        </div>
    )
}
