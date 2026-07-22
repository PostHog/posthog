// scenes/dashboard/TileFiltersOverride.tsx
import './TileFiltersOverride.scss'

import { useActions, useValues } from 'kea'

import { IconCalendar } from '@posthog/icons'
import { LemonSwitch } from '@posthog/lemon-ui'

import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { getProjectEventExistence } from 'lib/utils/getAppContext'

import { groupsModel } from '~/models/groupsModel'
import type { DashboardTile, QueryBasedInsightModel } from '~/types'

import { tileLogic } from './tileLogic'

export function TileFiltersOverride({ tile }: { tile: DashboardTile<QueryBasedInsightModel> }): JSX.Element {
    const { overrides } = useValues(tileLogic)
    const { setDates, setProperties, setIgnoreDashboardFilters } = useActions(tileLogic)
    const { groupsTaxonomicTypes } = useValues(groupsModel)

    const { hasPageview, hasScreen } = getProjectEventExistence()

    return (
        <div className="space-y-4 tile-filters-override">
            <div>
                <p className="text-sm text-muted mb-4">
                    Set custom filters for this tile. Property filters apply on top of the dashboard's, while the tile's
                    date range and breakdown replace the dashboard's.
                </p>
            </div>

            <div className="space-y-4">
                <div>
                    <LemonSwitch
                        checked={!!overrides.ignoreDashboardFilters}
                        onChange={setIgnoreDashboardFilters}
                        label="Ignore dashboard filters"
                        bordered
                        fullWidth
                        data-attr="tile-ignore-dashboard-filters"
                    />
                    <p className="text-xs text-muted mt-1 mb-0">
                        When on, none of the dashboard's filters apply to this insight. The overrides below still do.
                    </p>
                </div>

                <div>
                    <label className="text-sm font-medium mb-2 block">Date Range</label>
                    <DateFilter
                        showCustom
                        showExplicitDateToggle
                        dateFrom={overrides.date_from ?? null}
                        dateTo={overrides.date_to ?? null}
                        explicitDate={overrides.explicitDate}
                        onChange={(from, to, explicitDate) => setDates(from, to, explicitDate)}
                        makeLabel={(key) => (
                            <>
                                <IconCalendar />
                                <span className="hide-when-small"> {key}</span>
                            </>
                        )}
                    />
                </div>

                <div>
                    <label className="text-sm font-medium mb-2 block">Properties</label>
                    <PropertyFilters
                        onChange={(properties) => setProperties(properties)}
                        pageKey={`tile_${tile.id}_properties`}
                        propertyFilters={overrides.properties ?? []}
                        taxonomicGroupTypes={[
                            TaxonomicFilterGroupType.EventProperties,
                            TaxonomicFilterGroupType.PersonProperties,
                            TaxonomicFilterGroupType.EventFeatureFlags,
                            TaxonomicFilterGroupType.EventMetadata,
                            ...(hasPageview ? [TaxonomicFilterGroupType.PageviewUrls] : []),
                            ...(hasScreen ? [TaxonomicFilterGroupType.Screens] : []),
                            TaxonomicFilterGroupType.EmailAddresses,
                            ...groupsTaxonomicTypes,
                            TaxonomicFilterGroupType.Cohorts,
                            TaxonomicFilterGroupType.Elements,
                            TaxonomicFilterGroupType.SessionProperties,
                            TaxonomicFilterGroupType.HogQLExpression,
                            TaxonomicFilterGroupType.DataWarehousePersonProperties,
                        ]}
                    />
                </div>
            </div>
        </div>
    )
}
