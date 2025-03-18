import { midEllipsis } from 'lib/utils'

type HoqQLPropertyInfoProps = {
    value: string
}

export const HoqQLPropertyInfo = ({ value }: HoqQLPropertyInfoProps): JSX.Element => {
    return (
        <span title={value} className="font-mono text-accent-primary text-xs">
            {midEllipsis(value, 60)}
        </span>
    )
}
