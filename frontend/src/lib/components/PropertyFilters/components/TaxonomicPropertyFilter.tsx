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
import { propertyFilterLogic } from '../propertyFilterLogic'

export function TaxonomicPropertyFilter({
    index,
    onComplete,
    selectProps,
}: PropertyFilterInternalProps): JSX.Element {
    const { filters } = useValues(propertyFilterLogic)
    const { personProperties } = useValues(personPropertiesModel)
    const { setFilter } = useActions(propertyFilterLogic)
    const { key, value, operator, type } = filters[index]

    const displayOperatorAndValue = key && type !== 'cohort'

    return (
        <InfiniteSelectResults
            groups={[
                {
                    key: 'events',
                    name: 'Event properties',
                    type: 'event',
                    endpoint: 'api/projects/@current/property_definitions'
                },
                {
                    key: 'persons',
                    name: 'Person properties',
                    type: 'person',
                    dataSource: personProperties.map(property => ({
                        ...property,
                        key: property.name,
                    }))
                }
            ]}
            searchQuery={undefined}
            onSelect={(newType, _id, name) => {
                const newOperator = name === '$active_feature_flags' ? PropertyOperator.IContains : operator
                setFilter(
                    index,
                    name,
                    value || null,
                    newOperator || PropertyOperator.Exact,
                    newType,
                )
            }}
        />
    )
}
