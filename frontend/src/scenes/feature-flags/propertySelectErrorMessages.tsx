import { Fragment } from 'react'

import { IconErrorOutline } from 'lib/lemon-ui/icons'

// Matches the shape produced by featureFlagReleaseConditionsLogic's `propertySelectErrors`
// selector, one entry per condition set.
export type PropertySelectError = {
    properties?: { value?: string }[]
    rollout_percentage?: string
    variant: null
}

// Renders a condition set's property errors (from featureFlagReleaseConditionsLogic's
// `propertySelectErrors` selector) as the JSX.Element[] the PropertyFilters `errorMessages`
// prop expects, one entry per property (empty entries render nothing).
export function getPropertySelectErrorMessages(
    propertySelectErrors: PropertySelectError[] | null | undefined,
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
