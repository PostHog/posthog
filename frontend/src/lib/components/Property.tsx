import { Link } from '@posthog/lemon-ui'

import stringWithWBR from 'lib/utils/stringWithWBR'
import { isExternalLink } from 'lib/utils/url'

import { getPropertyValueUrl } from '~/taxonomy/propertySources'

export function Property({ value, propertyKey }: { value: any; propertyKey?: string }): JSX.Element {
    let valueString: string
    let valueComponent: JSX.Element | string
    if (typeof value === 'object') {
        valueString = valueComponent = JSON.stringify(value)
    } else {
        const externalUrl = getPropertyValueUrl(propertyKey, value) ?? (isExternalLink(value) ? String(value) : null)
        if (externalUrl) {
            valueString = String(value)
            valueComponent = (
                <span className="line-clamp-3 whitespace-normal">
                    <Link
                        to={externalUrl}
                        target="_blank"
                        className="value-link font-medium"
                        // The events table wraps the cell in a link that toggles a property filter,
                        // and that link cancels the click. Keep the two apart.
                        onClick={(e) => e.stopPropagation()}
                    >
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
