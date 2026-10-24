import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { getProjectEventExistence } from 'lib/utils/getAppContext'

/** The property groups that the dashboard property filter offers. */
export function dashboardPropertyFilterGroupTypes(
    groupsTaxonomicTypes: TaxonomicFilterGroupType[]
): TaxonomicFilterGroupType[] {
    const { hasPageview, hasScreen } = getProjectEventExistence()
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
        TaxonomicFilterGroupType.DataWarehousePersonProperties,
    ]
}
