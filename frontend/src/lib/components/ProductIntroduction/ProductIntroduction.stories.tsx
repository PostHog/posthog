import { Meta } from '@storybook/react'

import { GraphsHog } from 'lib/components/hedgehogs'

import { ProductKey } from '~/queries/schema/schema-general'

import { ProductIntroduction, ProductIntroductionProps } from './ProductIntroduction'

const meta: Meta<ProductIntroductionProps> = {
    title: 'Components/Product Empty State',
    component: ProductIntroduction,
}
export default meta

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
            thingName="history record"
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

/** Dashboard empty-state–style intro: matches `EmptyDashboardComponent` copy, with `GraphsHog` + responsive layout. */
function DashboardEmptyResponsiveIntro({
    useMainContentContainerQueries,
}: Partial<Pick<ProductIntroductionProps, 'useMainContentContainerQueries'>> = {}): JSX.Element {
    return (
        <ProductIntroduction
            productName="Dashboard"
            thingName="insight"
            titleOverride="So empty. So much potential."
            description="A simple first step is to add an insight from your library. Over time this becomes the home for the data you care about most."
            docsURL="https://posthog.com/docs/product-analytics/dashboards"
            action={() => alert('CTA clicked')}
            isEmpty={true}
            customHog={GraphsHog}
            hogLayout="responsive"
            useMainContentContainerQueries={useMainContentContainerQueries}
        />
    )
}

/** `hogLayout="responsive"`: hog stays visible on small viewports (stacked); switches to row from `md` up. */
export function hogLayoutResponsive(): JSX.Element {
    return <DashboardEmptyResponsiveIntro />
}

/**
 * Same as `hogLayoutResponsive`, but breakpoints come from the `main-content` container (as in navigation),
 * not the viewport — so a narrow main column stays stacked even when the Storybook canvas is wide.
 */
export function hogLayoutResponsiveWithMainContentContainerQueries(): JSX.Element {
    return (
        <div className="flex flex-col gap-6">
            <p className="text-secondary text-sm m-0">
                Left: main-content width under 48rem → stacked. Right: over 48rem → row (hog beside copy).
            </p>
            <div className="flex flex-wrap items-start gap-6">
                <div className="flex flex-col gap-2">
                    <span className="text-xs font-medium text-secondary">Narrow @container/main-content (288px)</span>
                    <div
                        className="@container/main-content w-72 shrink-0 rounded-lg border border-primary bg-bg-light p-3"
                        data-attr="storybook-main-content-narrow"
                    >
                        <DashboardEmptyResponsiveIntro useMainContentContainerQueries />
                    </div>
                </div>
                <div className="flex flex-col gap-2">
                    <span className="text-xs font-medium text-secondary">Wide @container/main-content (800px)</span>
                    <div
                        className="@container/main-content w-[800px] max-w-full shrink-0 rounded-lg border border-primary bg-bg-light p-3 overflow-x-auto"
                        data-attr="storybook-main-content-wide"
                    >
                        <DashboardEmptyResponsiveIntro useMainContentContainerQueries />
                    </div>
                </div>
            </div>
        </div>
    )
}

hogLayoutResponsiveWithMainContentContainerQueries.parameters = {
    docs: {
        description: {
            story: 'Uses `@container/main-content` like `#main-content` in `Navigation.tsx`, so layout tracks the main column when the side panel narrows it.',
        },
    },
}
