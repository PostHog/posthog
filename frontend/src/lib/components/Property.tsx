import { Link } from '@posthog/lemon-ui'

import { isExternalLink } from 'lib/utils'

export function Property({ value }: { value: any }): JSX.Element {
    let valueString: string
    let valueComponent: JSX.Element | string
    if (typeof value === 'object') {
        valueString = valueComponent = JSON.stringify(value)
    } else {
        if (isExternalLink(value)) {
            valueString = value
            valueComponent = (
                <Link to={valueString} target="_blank">
                    {value}
                </Link>
            )
        } else {
            valueString = valueComponent = String(value)
        }
    }
    return <span title={valueString}>{valueComponent}</span>
}
