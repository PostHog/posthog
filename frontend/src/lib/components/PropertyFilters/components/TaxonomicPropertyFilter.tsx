/*
Contains the property filter component w/ properties and cohorts separated in tabs. Also includes infinite-scroll remote loading.
*/
import React, { useState } from 'react'
import { Col, Row, Select, Tabs } from 'antd'
import { keyMapping } from 'lib/components/PropertyKeyInfo'
import { cohortsModel } from '~/models/cohortsModel'
import { useValues, useActions } from 'kea'
import { SelectGradientOverflow, SelectGradientOverflowProps } from 'lib/components/SelectGradientOverflow'
import { Link } from '../../Link'
import { PropertySelect } from './PropertySelect'
import { OperatorValueSelect } from './OperatorValueSelect'
import { isOperatorMulti, isOperatorRegex } from 'lib/utils'
import { PropertyOptionGroup } from './PropertySelect'
import { PropertyOperator } from '~/types'
import { PropertyFilterInternalProps } from './PropertyFilter'
import { personPropertiesModel } from '~/models/personPropertiesModel'
import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'
import { InfiniteSelectResults } from './InfiniteSelectResults'

export function TaxonomicPropertyFilter({
    index,
    onComplete,
    logic,
    selectProps,
}: PropertyFilterInternalProps): JSX.Element {
    const { filters } = useValues(logic)
    const { setFilter } = useActions(logic)
    const { key, value, operator, type } = filters[index]
    const [activeKey, setActiveKey] = useState(type === 'cohort' ? 'cohort' : 'property')

    const displayOperatorAndValue = key && type !== 'cohort'

    const setThisFilter = (newKey: string, newValue: string | undefined, newOperator: string, newType: string): void => {
        setFilter(index, newKey, newValue, newOperator, newType)
    }

    return (
        <InfiniteSelectResults
            groups={[{
                key: 'events',
                name: 'Event properties',
                type: 'event',
                endpoint: 'api/projects/@current/property_definitions'
            }]}
            searchQuery={undefined}
            onSelect={(newType, newValue, name) => {
                setThisFilter(
                    newValue.toString(),
                    undefined,
                    newValue === '$active_feature_flags' ? 'icontains' : operator,
                    newType,
                )
            }}
        />
    )
}
