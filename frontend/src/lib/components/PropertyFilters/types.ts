import { OperatorValueSelectProps } from 'lib/components/PropertyFilters/components/OperatorValueSelect'
import {
    AllowedProperties,
    ExcludedOperators,
    ExcludedProperties,
    SelectingKeyOnly,
    TaxonomicFilterGroup,
    TaxonomicFilterGroupType,
    TaxonomicFilterProps,
    TaxonomicFilterValue,
} from 'lib/components/TaxonomicFilter/types'

import { PropValue } from '~/models/propertyDefinitionsModel'
import { AnyDataNode, DatabaseSchemaField } from '~/queries/schema/schema-general'
import { AnyPropertyFilter, FilterLogicalOperator, PropertyDefinition, PropertyGroupFilter } from '~/types'

export interface PropertyFilterBaseProps {
    pageKey: string
}

export interface PropertyFilterLogicProps extends PropertyFilterBaseProps {
    propertyFilters?: AnyPropertyFilter[] | null
    onChange: (filters: AnyPropertyFilter[]) => void
    sendAllKeyUpdates?: boolean
}

export interface PropertyGroupFilterLogicProps extends PropertyFilterBaseProps {
    value?: PropertyGroupFilter
    onChange: (filters: PropertyGroupFilter) => void
}
export interface TaxonomicPropertyFilterLogicProps extends PropertyFilterBaseProps {
    taxonomicGroupTypes: TaxonomicFilterGroupType[]
    taxonomicOnChange?: (group: TaxonomicFilterGroup, value: TaxonomicFilterValue, item: any) => void
    filters: AnyPropertyFilter[]
    setFilter: (index: number, property: AnyPropertyFilter) => void
    filterIndex: number
    eventNames?: string[]
    excludedProperties?: ExcludedProperties
    propertyAllowList?: AllowedProperties
    endpointFilters?: Record<string, any>
}

export interface PropertyFilterInternalProps {
    pageKey?: string
    index: number
    onComplete: () => void
    disablePopover: boolean
    filters: AnyPropertyFilter[]
    setFilter: (index: number, property: AnyPropertyFilter) => void
    editable?: boolean
    operatorAllowlist?: OperatorValueSelectProps['operatorAllowlist']
    taxonomicGroupTypes?: TaxonomicFilterGroupType[]
    taxonomicFilterOptionsFromProp?: TaxonomicFilterProps['optionsFromProp']
    propertyAllowList?: AllowedProperties
    eventNames?: string[]
    schemaColumns?: DatabaseSchemaField[]
    dataWarehouseTableName?: string
    propertyGroupType?: FilterLogicalOperator | null
    orFiltering?: boolean
    addText?: string | null
    size?: 'xsmall' | 'small' | 'medium'
    hasRowOperator?: boolean
    metadataSource?: AnyDataNode
    excludedProperties?: ExcludedProperties
    allowRelativeDateOptions?: boolean
    excludedOperators?: ExcludedOperators
    selectingKeyOnly?: SelectingKeyOnly
    hideBehavioralCohorts?: boolean
    addFilterDocLink?: string
    endpointFilters?: Record<string, any>
    hogQLGlobals?: Record<string, any>
    /**
     * `'input'` renders the replay-style input-box add-filter trigger; `'button'`
     * (the default) renders a button. Only has an effect on the rebuild menu
     * (`TAXONOMIC_FILTER_MENU_REBUILD`).
     */
    triggerVariant?: 'button' | 'input'
    /**
     * Statically known value suggestions per property key, replacing API-fetched ones.
     * Return an empty array to disable suggestions for a key, or null to fall back
     * to the default behavior. See `PropertyValueProps.staticValues`.
     */
    staticValueOptions?: (propertyKey: string) => PropValue[] | null
    /** Override the model's inferred definitions, e.g. for a polymorphic event property. */
    propertyDefinitionsOverride?: PropertyDefinition[]
    /** Keep the selected property key fixed while allowing operator/value edits. */
    propertyKeyEditable?: boolean
    /** Keep key, operator, and value controls on one row when the host has enough width. */
    singleLine?: boolean
}
