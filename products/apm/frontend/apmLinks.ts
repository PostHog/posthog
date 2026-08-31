// Cross-facet links. Pivoting between signals for one service is the whole point of putting
// them behind one product, and today only some of those pivots exist: a log row can reach a
// trace and a metric exemplar can reach a trace, but nothing links logs and metrics at all.
// Routing every pivot through the APM shell makes them uniform, because a facet is a parameter
// rather than a separate destination.

import { combineUrl } from 'kea-router'

import { urls } from 'scenes/urls'

import type { DateRange } from '~/queries/schema/schema-general'

import { DEFAULT_APM_TAB, type ApmSceneTab } from './apmSceneLogic'

export interface ApmScope {
    /** Scopes every facet to one service, the join key all three signals already carry. */
    serviceName?: string | null
    dateRange?: DateRange | null
}

/**
 * Link into an APM facet, optionally scoped to a service and time window.
 *
 * Defaults are left out of the URL so a shared link carries only what the sender actually
 * chose. The parameter names match what `apmSceneLogic` reads back.
 */
export function apmFacetUrl(tab: ApmSceneTab, scope: ApmScope = {}): string {
    const params: Record<string, string> = {}

    if (tab !== DEFAULT_APM_TAB) {
        params.tab = tab
    }
    if (scope.serviceName) {
        params.serviceNames = JSON.stringify([scope.serviceName])
    }
    if (scope.dateRange) {
        params.dateRange = JSON.stringify(scope.dateRange)
    }

    return combineUrl(urls.apm(), params).url
}
