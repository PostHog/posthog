import { LemonProgress } from 'lib/lemon-ui/LemonProgress'

import { CountCell } from './CountCell'

export interface VolumeCellProps {
    value: number
    /** The largest value on the page, which fills the bar. */
    max: number
}

export function VolumeCell({ value, max }: VolumeCellProps): JSX.Element {
    return (
        <div className="flex flex-col items-end gap-1">
            <CountCell value={value} />
            <div className="w-16">
                <LemonProgress
                    percent={max > 0 ? (value / max) * 100 : 0}
                    bgColor="var(--color-border-primary)"
                    strokeColor="var(--color-text-tertiary)"
                    smoothing={false}
                />
            </div>
        </div>
    )
}
