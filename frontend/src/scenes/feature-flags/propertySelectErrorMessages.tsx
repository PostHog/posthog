import { DeepPartialMap, ValidationErrorType } from 'kea-forms'
import { Fragment } from 'react'

import { IconErrorOutline } from 'lib/lemon-ui/icons'

import { FeatureFlagGroupType } from '~/types'

// Renders a condition set's property errors (from featureFlagReleaseConditionsLogic's
// `propertySelectErrors` selector) as the JSX.Element[] the PropertyFilters `errorMessages`
// prop expects, one entry per property (empty entries render nothing).
export function getPropertySelectErrorMessages(
    propertySelectErrors: DeepPartialMap<FeatureFlagGroupType, ValidationErrorType>[] | null,
    index: number
): JSX.Element[] | null {
    const properties = propertySelectErrors?.[index]?.properties
    if (!properties) {
        return null
    }
    let hasError = false
    const messages = properties.map((message, messageIndex) => {
        if (typeof message?.value !== 'string') {
            return <Fragment key={messageIndex} />
        }
        hasError = true
        return (
            <div key={messageIndex} className="text-danger flex items-center gap-1 text-sm Field--error">
                <IconErrorOutline className="text-xl" /> {message.value}
            </div>
        )
    })
    return hasError ? messages : null
}
