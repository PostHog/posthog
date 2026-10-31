import { IconInfo } from '@posthog/icons'
import { Tooltip } from '@posthog/lemon-ui'

export interface ChartOptionLabelProps {
    label: string
    info?: string
}

export function ChartOptionLabel({ label, info }: ChartOptionLabelProps): JSX.Element {
    return (
        <span className="font-normal">
            {label}
            {info && (
                <>
                    {' '}
                    <Tooltip title={info}>
                        <IconInfo className="relative top-0.5 text-lg text-secondary" />
                    </Tooltip>
                </>
            )}
        </span>
    )
}
