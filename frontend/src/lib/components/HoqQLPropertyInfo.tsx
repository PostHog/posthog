import { midEllipsis } from 'lib/utils'

type HoqQLPropertyInfoProps = {
    value: string
}

export const HoqQLPropertyInfo = ({ value }: HoqQLPropertyInfoProps): JSX.Element => {
    return (
        <span title={value} className="text-accent font-mono text-xs">
            {midEllipsis(value, 60)}
        </span>
    )
}
