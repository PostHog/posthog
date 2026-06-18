import { Link } from '@posthog/lemon-ui'

import stringWithWBR from 'lib/utils/stringWithWBR'
import { isExternalLink } from 'lib/utils/url'

export function Property({ value }: { value: any }): JSX.Element {
    let valueString: string
    let valueComponent: JSX.Element | string
    if (typeof value === 'object') {
        valueString = valueComponent = JSON.stringify(value)
    } else {
        if (isExternalLink(value)) {
            valueString = value
            valueComponent = (
                <span className="line-clamp-3 whitespace-normal">
                    <Link to={valueString} target="_blank" className="value-link font-medium">
                        {stringWithWBR(valueString, 20)}
                    </Link>
                </span>
            )
        } else {
            valueString = valueComponent = String(value)
        }
    }
    return <span title={valueString}>{valueComponent}</span>
}
