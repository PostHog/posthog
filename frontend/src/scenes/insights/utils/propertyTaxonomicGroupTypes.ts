import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'

export function getInsightPropertyFilterGroupTypes({
    groupsTaxonomicTypes,
    hasPageview,
    hasScreen,
    includeDataWarehouseProperties = false,
}: {
    groupsTaxonomicTypes: TaxonomicFilterGroupType[]
    hasPageview: boolean
    hasScreen: boolean
    includeDataWarehouseProperties?: boolean
}): TaxonomicFilterGroupType[] {
    return [
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
        ...(includeDataWarehouseProperties ? [TaxonomicFilterGroupType.DataWarehouseProperties] : []),
        TaxonomicFilterGroupType.DataWarehousePersonProperties,
    ]
}
