import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'

export const commonActionFilterProps = {
    // Offers events whose data is moving out of the events table. Exposure is still measured with
    // $feature_flag_called, and every picker spreading this object shares the setting, so metric
    // definitions get it too. A metric saved on such an event stops returning data once the move
    // happens. Drop this once ingestion duplicates multivariate $feature_flag_called into
    // $experiment_exposure for every team and exposure reads that event instead.
    includeHiddenEvents: true,
    actionsTaxonomicGroupTypes: [
        TaxonomicFilterGroupType.Events,
        TaxonomicFilterGroupType.Actions,
        TaxonomicFilterGroupType.DataWarehouse,
    ],
    propertiesTaxonomicGroupTypes: [
        TaxonomicFilterGroupType.EventProperties,
        TaxonomicFilterGroupType.PersonProperties,
        TaxonomicFilterGroupType.EventFeatureFlags,
        TaxonomicFilterGroupType.Cohorts,
        TaxonomicFilterGroupType.Elements,
        TaxonomicFilterGroupType.SessionProperties,
        TaxonomicFilterGroupType.HogQLExpression,
        TaxonomicFilterGroupType.DataWarehouseProperties,
        TaxonomicFilterGroupType.DataWarehousePersonProperties,
    ],
}
