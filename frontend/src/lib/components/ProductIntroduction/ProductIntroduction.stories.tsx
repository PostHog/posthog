import { ComponentMeta } from '@storybook/react'
import { ProductIntroduction } from './ProductIntroduction'
import { ProductKey } from '~/types'

export default {
    title: 'Components/Product Empty State',
    component: ProductIntroduction,
} as ComponentMeta<typeof ProductIntroduction>

export function ProductIntroduction_(): JSX.Element {
    return (
        <ProductIntroduction
            productName="Cohorts"
            productKey={ProductKey.COHORTS}
            thingName="cohort"
            description="Use cohorts to group people together, such as users who used your app in the last week, or people who viewed the signup page but didn’t convert."
            docsURL="https://posthog.com/docs/data/cohorts"
            action={() => alert('You clicked the button!')}
            isEmpty={true}
        />
    )
}

export function emptyWithAction(): JSX.Element {
    return (
        <ProductIntroduction
            productName="Cohorts"
            productKey={ProductKey.COHORTS}
            thingName="cohort"
            description="Use cohorts to group people together, such as users who used your app in the last week, or people who viewed the signup page but didn’t convert."
            docsURL="https://posthog.com/docs/data/cohorts"
            action={() => alert('You clicked the button!')}
            isEmpty={true}
        />
    )
}

export function emptyNoAction(): JSX.Element {
    return (
        <ProductIntroduction
            productName="Feature Flags"
            productKey={ProductKey.FEATURE_FLAGS}
            thingName={'history record'}
            description={`History shows any feature flag changes that have been made. After making changes you'll see them logged here.`}
        />
    )
}

export function notEmptyWithAction(): JSX.Element {
    return (
        <ProductIntroduction
            productName="Cohorts"
            productKey={ProductKey.COHORTS}
            thingName="cohort"
            description="Use cohorts to group people together, such as users who used your app in the last week, or people who viewed the signup page but didn’t convert."
            docsURL="https://posthog.com/docs/data/cohorts"
            action={() => alert('You clicked the button!')}
            isEmpty={false}
        />
    )
}
