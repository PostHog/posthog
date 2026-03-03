import { connect, kea, key, path, props, selectors } from 'kea'

import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'
import { PropertyDefinitionType } from '~/types'

import type { propertyValueLogicType } from './propertyValueLogicType'

export interface PropertyValueLogicProps {
    propertyKey: string
    type: PropertyDefinitionType
}

export const propertyValueLogic = kea<propertyValueLogicType>([
    path(['lib', 'components', 'PropertyFilters', 'propertyValueLogic']),
    props({} as PropertyValueLogicProps),
    key((props) => `${props.type}/${props.propertyKey}`),
    connect(() => ({ values: [propertyDefinitionsModel, ['options']] })),
    selectors(({ props }) => ({
        propertyOption: [(s) => [s.options], (options) => options[props.propertyKey]],
        /** Whether a background cache refresh is currently in progress for this property. */
        isRefreshing: [(s) => [s.propertyOption], (propertyOption): boolean => propertyOption?.refreshing ?? false],
    })),
])
