import { useActions, useValues } from 'kea'

import { Link, Spinner } from '@posthog/lemon-ui'

import { Facet } from 'lib/components/FacetRail/Facet'
import { FacetRail } from 'lib/components/FacetRail/FacetRail'

import { platformAlertsLogic } from './platformAlertsLogic'

/** The alerts list's filter rail: state, mute, type, and each label key, with how many alerts have each value. */
export function PlatformAlertsFacetRail(): JSX.Element | null {
    const { railFacets, filters, facetNameSearch, railCollapsed, facets, facetsLoading, facetsError } =
        useValues(platformAlertsLogic)
    const { toggleFilterValue, setFacetNameSearch, setRailCollapsed, loadFacets } = useActions(platformAlertsLogic)

    if (railCollapsed) {
        return null
    }
    return (
        <FacetRail
            notice={
                facetsError ? (
                    <div className="px-1 pb-2 text-xs text-secondary" data-attr="platform-alerts-facet-rail-error">
                        Couldn't load the filters.{' '}
                        <Link onClick={() => loadFacets()} data-attr="platform-alerts-facet-rail-retry">
                            Retry
                        </Link>
                    </div>
                ) : facets === null && facetsLoading ? (
                    <Spinner />
                ) : null
            }
            facets={railFacets}
            renderFacet={(facet, hidden) =>
                hidden ? (
                    <></>
                ) : (
                    <Facet
                        title={facet.title}
                        options={facet.options}
                        selected={filters[facet.param]}
                        onToggle={(value) => toggleFilterValue(facet.param, value)}
                        dataAttrPrefix="platform-alerts-facet"
                        zeroCountReason="No alerts have this value"
                        dimZeroCounts
                    />
                )
            }
            facetNameSearch={facetNameSearch}
            onFacetNameSearchChange={setFacetNameSearch}
            onCollapsedChange={setRailCollapsed}
            // pinned: the saved rail width lives under these keys
            resizerLogicKey="platform-alerts-facet-rail"
            resizerPersistPrefix="2026-11-27"
            dataAttrPrefix="platform-alerts-facet-rail"
        />
    )
}
