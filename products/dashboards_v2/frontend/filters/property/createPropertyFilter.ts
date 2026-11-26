import { createElement } from 'react'

import {
    type FilterControlProps,
    type FilterDefinition,
    type FilterPickerProps,
    defineFilter,
} from '../filterDefinition'
import { PropertyFilter } from './PropertyFilter'
import { PropertyFilterPicker, type PropertySearch } from './PropertyFilterPicker'
import {
    type FeaturedProperty,
    type PropertyFilterConfig,
    type PropertyFilterValue,
    type PropertyValues,
    propertyFilterSpec,
} from './propertyFilterSpec'

/**
 * A filter on an event or person property. `featured` are the properties the add menu names, so a product can put the
 * ones it cares about first. `search` adds a menu entry that finds any other property the product offers, such as
 * its own custom events. Left out, only the featured properties can be added. `values` suggests
 * values to pick, with counts; left out, the person types each value.
 */
export function createPropertyFilter({
    featured = [],
    search,
    values,
}: { featured?: FeaturedProperty[]; search?: PropertySearch; values?: PropertyValues } = {}): FilterDefinition {
    return defineFilter<PropertyFilterConfig, PropertyFilterValue>({
        ...propertyFilterSpec(featured, search?.label),
        Control: (props: FilterControlProps<PropertyFilterConfig, PropertyFilterValue>) =>
            createElement(PropertyFilter, { ...props, values }),
        Picker: search
            ? (props: FilterPickerProps<PropertyFilterConfig>) =>
                  createElement(PropertyFilterPicker, { ...props, search })
            : undefined,
    })
}
