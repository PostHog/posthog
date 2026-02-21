import { connect, kea, key, path, props, selectors } from 'kea'

import { toString } from 'lib/utils'

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
        /**
         * Names of values that appeared after the latest background refresh completed.
         * Empty while the user has a search query active (to avoid false positives).
         */
        newValueNames: [
            (s) => [s.propertyOption],
            (propertyOption): Set<string> => {
                if (!propertyOption?.preRefreshValueNames?.length || propertyOption?.searchInput) {
                    return new Set()
                }
                const baselineSet = new Set(propertyOption.preRefreshValueNames)
                return new Set(
                    (propertyOption?.values || []).map((v) => toString(v.name)).filter((name) => !baselineSet.has(name))
                )
            },
        ],
    })),
])
