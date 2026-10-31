import { IconInfo } from '@posthog/icons'
import { Tooltip } from '@posthog/lemon-ui'

export interface ChartOptionLabelProps {
    label: string
    info?: string
    /** The id of the input this label names. */
    htmlFor?: string
}

export function ChartOptionLabel({ label, info, htmlFor }: ChartOptionLabelProps): JSX.Element {
    const Element = htmlFor ? 'label' : 'span'
    return (
        <Element className="font-normal" htmlFor={htmlFor}>
            {label}
            {info && (
                <>
                    {' '}
                    <Tooltip title={info}>
                        <IconInfo className="relative top-0.5 text-lg text-secondary" />
                    </Tooltip>
                </>
            )}
        </Element>
    )
}
