import { Meta, StoryFn } from '@storybook/react'
import { useActions, useMountedLogic, useValues } from 'kea'
import { useState } from 'react'

import { actionsModel } from '~/models/actionsModel'
import { cohortsModel } from '~/models/cohortsModel'

import { taxonomicFilterMocksDecorator } from '../TaxonomicFilter/__mocks__/taxonomicFilterMocksDecorator'
import { TaxonomicFilterGroupType } from '../TaxonomicFilter/types'
import UniversalFilters from './UniversalFilters'
import { DEFAULT_UNIVERSAL_GROUP_FILTER, universalFiltersLogic } from './universalFiltersLogic'
import { isUniversalGroupFilterLike } from './utils'

const meta: Meta<typeof UniversalFilters> = {
    title: 'Filters/Universal Filters',
    component: UniversalFilters,
    decorators: [taxonomicFilterMocksDecorator],
}
export default meta

// When implementing UniversalFilters, customize this to render your own UI
const NestedFilterGroup = ({ rootKey }: { rootKey: string }): JSX.Element => {
    const { rootKey: currentKey, filterGroup } = useValues(universalFiltersLogic)
    const { replaceGroupValue, removeGroupValue } = useActions(universalFiltersLogic)

    return (
        <div className="border">
            <div>Is root: {String(rootKey === currentKey)}</div>
            <div>{JSON.stringify(filterGroup)}</div>
            {filterGroup.values.map((filterOrGroup, index) => {
                return isUniversalGroupFilterLike(filterOrGroup) ? (
                    <UniversalFilters.Group key={index} index={index} group={filterOrGroup}>
                        <NestedFilterGroup rootKey={rootKey} />
                    </UniversalFilters.Group>
                ) : (
                    <UniversalFilters.Value
                        key={index}
                        index={index}
                        filter={filterOrGroup}
                        onRemove={() => removeGroupValue(index)}
                        onChange={(value) => replaceGroupValue(index, value)}
                    />
                )
            })}
            <UniversalFilters.AddFilterButton />
        </div>
    )
}

export const Default: StoryFn<typeof UniversalFilters> = ({ group }) => {
    const [filterGroup, setFilterGroup] = useState(group)
    useMountedLogic(cohortsModel)
    useMountedLogic(actionsModel)

    const rootKey = 'session-recordings'

    return (
        <UniversalFilters
            rootKey={rootKey}
            group={filterGroup}
            taxonomicGroupTypes={[
                TaxonomicFilterGroupType.Events,
                TaxonomicFilterGroupType.Actions,
                TaxonomicFilterGroupType.Cohorts,
                TaxonomicFilterGroupType.PersonProperties,
                TaxonomicFilterGroupType.SessionProperties,
            ]}
            onChange={(filterGroup) => {
                setFilterGroup(filterGroup)
            }}
        >
            <NestedFilterGroup rootKey={rootKey} />
        </UniversalFilters>
    )
}
Default.args = {
    group: DEFAULT_UNIVERSAL_GROUP_FILTER,
}
