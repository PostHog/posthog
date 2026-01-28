// scenes/dashboard/TileFiltersOverride.tsx
import './TileFiltersOverride.scss'

import { useActions, useValues } from 'kea'

import { IconCalendar } from '@posthog/icons'
import '@posthog/lemon-ui'

import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { groupsModel } from '~/models/groupsModel'
import type { DashboardTile, QueryBasedInsightModel } from '~/types'

import { tileLogic } from './tileLogic'

export function TileFiltersOverride({ tile }: { tile: DashboardTile<QueryBasedInsightModel> }): JSX.Element {
    const { overrides } = useValues(tileLogic)
    const { setDates, setProperties } = useActions(tileLogic)
    const { groupsTaxonomicTypes } = useValues(groupsModel)

    const { featureFlags } = useValues(featureFlagLogic)
    const canAccessExplicitDateToggle = !!featureFlags[FEATURE_FLAGS.PRODUCT_ANALYTICS_DATE_PICKER_EXPLICIT_DATE_TOGGLE]

    return (
        <div className="space-y-4 tile-filters-override">
            <div>
                <p className="text-sm text-muted mb-4">
                    Set custom filters for this tile that will override all other filters.
                </p>
            </div>

            <div className="space-y-4">
                <div>
                    <label className="text-sm font-medium mb-2 block">Date Range</label>
                    <DateFilter
                        showCustom
                        showExplicitDateToggle={canAccessExplicitDateToggle}
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
