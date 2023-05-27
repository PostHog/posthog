import { ComponentMeta } from '@storybook/react'
import { ProductEmptyState } from './ProductEmptyState'

export default {
    title: 'Components/Product Empty State',
    component: ProductEmptyState,
} as ComponentMeta<typeof ProductEmptyState>

export function ProductEmptyState_(): JSX.Element {
    return (
        <ProductEmptyState
            productName="Cohorts"
            thingName="cohort"
            description="Use cohorts to group people together, such as users who used your app in the last week, or people who viewed the signup page but didn’t convert."
            docsURL="https://posthog.com/docs/data/cohorts"
            action={() => alert('You clicked the button!')}
        />
    )
}

export function withAction(): JSX.Element {
    return (
        <ProductEmptyState
            productName="Cohorts"
            thingName="cohort"
            description="Use cohorts to group people together, such as users who used your app in the last week, or people who viewed the signup page but didn’t convert."
            docsURL="https://posthog.com/docs/data/cohorts"
            action={() => alert('You clicked the button!')}
        />
    )
}

export function noAction(): JSX.Element {
    return (
        <ProductEmptyState
            productName="Feature Flags"
            thingName={'history for feature flag'}
            description={`History shows any changes that were made to feature flags. As changes are made they'll show up here.`}
        />
    )
}
