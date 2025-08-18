import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import posthog from 'posthog-js'

import { LemonBanner } from 'lib/lemon-ui/LemonBanner'

import { ProductTab } from './common'
import { webAnalyticsLogic } from './webAnalyticsLogic'

export const WebAnalyticsPageReportsCTA = (): JSX.Element | null => {
    const { webAnalyticsFilters, productTab, domainFilter, authorizedDomains } = useValues(webAnalyticsLogic)
    const { setProductTab } = useActions(webAnalyticsLogic)

    const pageFilter = webAnalyticsFilters?.find((filter) => filter.key === '$pathname')
    const hasSingleDomain = authorizedDomains.length === 1
    const hasSpecificDomain = domainFilter && domainFilter !== 'all'

    if (!pageFilter || productTab !== ProductTab.ANALYTICS || (!hasSpecificDomain && !hasSingleDomain)) {
        return null
    }

    const handleOptIn = (): void => {
        const domainToUse = hasSpecificDomain ? domainFilter : authorizedDomains[0]
        posthog.updateEarlyAccessFeatureEnrollment('web-analytics-page-reports', true)

        // Wait a bit for the feature flag to be applied
        setTimeout(() => {
            setProductTab(ProductTab.PAGE_REPORTS)
            router.actions.push('/web/page-reports', { pageURL: `${domainToUse}${pageFilter.value}` })
        }, 100)
    }

    return (
        <LemonBanner
            type="info"
            className="mt-2"
            action={{
                onClick: handleOptIn,
                children: 'Let me check it out!',
            }}
            onClose={() => {}} // Just closing, if people complain we can use a dissmissKey so it won't show again
        >
            <p>
                It looks like you're filtering by a specific page. We have a new Page Reports feature in early access
                that gives you detailed insights about individual pages.
            </p>
        </LemonBanner>
    )
}
