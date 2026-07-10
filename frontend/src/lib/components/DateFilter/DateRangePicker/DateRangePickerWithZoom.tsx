import { IconMinusSquare, IconPlusSquare } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { DateRangePicker, DateRangePickerProps } from './DateRangePicker'
import { zoomDateRange } from './zoom-utils'

export interface DateRangePickerWithZoomProps extends DateRangePickerProps {
    /**
     * Override how zoom is applied. When omitted, zoom multiplies the current range via `zoomDateRange`
     * and calls `setDateRange`. Provide this to route zoom through a logic action that also fires
     * analytics or triggers side effects (e.g. reloading a histogram).
     */
    onZoom?: (multiplier: number) => void
}

/**
 * Date range picker flanked by zoom-out / zoom-in buttons, fused into a single control via the
 * `DateRangePickerButtonGroup` wrapper (squared inner corners, rounded outer corners). The picker's
 * trigger button is a direct DOM child of the group — `Popover` clones rather than wraps it — so the
 * group's `> .LemonButton` styling treats all three buttons as one seamless unit.
 */
export const DateRangePickerWithZoom = ({ onZoom, ...pickerProps }: DateRangePickerWithZoomProps): JSX.Element => {
    const handleZoom = (multiplier: number): void => {
        if (onZoom) {
            onZoom(multiplier)
            return
        }
        const zoomed = zoomDateRange(pickerProps.dateRange, multiplier)
        pickerProps.setDateRange({ date_from: zoomed.date_from ?? null, date_to: zoomed.date_to ?? null })
    }

    return (
        <div className="DateRangePickerButtonGroup">
            <LemonButton
                size="small"
                icon={<IconMinusSquare />}
                type="secondary"
                tooltip="Zoom out"
                onClick={() => handleZoom(2)}
            />
            <DateRangePicker {...pickerProps} />
            <LemonButton
                size="small"
                icon={<IconPlusSquare />}
                type="secondary"
                tooltip="Zoom in"
                onClick={() => handleZoom(0.5)}
            />
        </div>
    )
}
