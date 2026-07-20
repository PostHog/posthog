import { combineUrl } from 'kea-router'

import { toParams } from 'lib/utils/url'

// The toolbar's own copy of the `urls` helpers it links to in the PostHog app. The app's
// `scenes/urls.ts` spreads every product manifest into its `urls` object, which would pull the
// entire product scene graph into the customer-facing toolbar bundle — so toolbar code imports
// this deliberate duplicate instead. `urls.test.ts` asserts each helper stays byte-identical
// with the app implementation; add the matching sample there when you add a helper here.
export const urls = {
    action: (id: string | number): string => `/data-management/actions/${id}`,
    actions: (): string => '/data-management/actions',
    experiment: (
        id: string | number,
        formMode?: string | null,
        options?: {
            name?: string
        }
    ): string => {
        const baseUrl = formMode ? `/experiments/${id}/${formMode}` : `/experiments/${id}`
        return `${baseUrl}${options ? `?${toParams(options)}` : ''}`
    },
    experiments: (): string => '/experiments',
    featureFlag: (id: string | number): string => `/feature_flags/${id}`,
    featureFlags: (tab?: string): string => `/feature_flags${tab ? `?tab=${tab}` : ''}`,
    productTour: (id: string, params?: string): string =>
        `/product_tours/${id}${params ? `?${params.startsWith('?') ? params.slice(1) : params}` : ''}`,
    sessionProfile: (id: string): string => `/sessions/${id}`,
    settings: (section: string = 'project', setting?: string): string =>
        combineUrl(`/settings/${section}`, undefined, setting).url,
    survey: (id: string): string => `/surveys/${id}`,
    surveys: (tab?: string): string => `/surveys${tab ? `?tab=${tab}` : ''}`,
    webAnalyticsWebVitals: (): string => `/web/web-vitals`,
}

// Deliberate stub, NOT parity-tested: the app's urlToResource walks a matcher tree built from
// every product manifest's fileSystemTypes. Its only consumer shipped in the toolbar is Link's
// drag-to-notebook annotation, which doesn't apply on customer pages — null disables it.
export function urlToResource(_url: string): { type: string; ref: string } | null {
    return null
}
