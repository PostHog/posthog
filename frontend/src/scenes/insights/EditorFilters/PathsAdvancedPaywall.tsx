import React from 'react'
import { AvailableFeature, EditorFilterProps } from '~/types'

import { PayCard } from 'lib/components/PayCard/PayCard'

export function PathsAdvancedPaywall({}: EditorFilterProps): JSX.Element {
    return (
        <PayCard
            identifier={AvailableFeature.PATHS_ADVANCED}
            title="Get a deeper understanding of your users"
            caption="Advanced features such as interconnection with funnels, grouping &amp; wildcarding and exclusions can help you gain deeper insights."
            docsLink="https://posthog.com/docs/user-guides/paths"
            dismissable={false}
        />
    )
}
