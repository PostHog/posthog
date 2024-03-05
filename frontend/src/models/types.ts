import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'

export interface PersonPropertiesModelProps {
    propertyAllowList?: { [key in TaxonomicFilterGroupType]?: string[] } // only return properties in this list, currently only working for EventProperties and PersonProperties
}
