import { Sparkline } from 'lib/components/Sparkline'

export interface VolumeCellProps {
    /** One count per bucket. */
    values: number[]
    labels: string[]
    name: string
    color?: 'muted' | 'danger' | 'primary'
    className?: string
}

export function VolumeCell({
    values,
    labels,
    name,
    color = 'muted',
    className = 'h-8 w-40',
}: VolumeCellProps): JSX.Element {
    return <Sparkline data={values} labels={labels} name={name} color={color} type="bar" className={className} />
}
