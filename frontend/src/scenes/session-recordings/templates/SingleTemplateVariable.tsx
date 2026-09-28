import { useActions, useMountedLogic, useValues } from 'kea'

import { LemonInput, LemonLabel } from '@posthog/lemon-ui'

import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import UniversalFilters from 'lib/components/UniversalFilters/UniversalFilters'
import { universalFiltersLogic } from 'lib/components/UniversalFilters/universalFiltersLogic'
import { isUniversalGroupFilterLike } from 'lib/components/UniversalFilters/utils'

import { actionsModel } from '~/models/actionsModel'
import { FilterLogicalOperator, ReplayTemplateVariableType } from '~/types'

import { ReplayTemplateLogicPropsType, sessionReplayTemplatesLogic } from './sessionRecordingTemplatesLogic'

const NestedFilterGroup = ({ buttonTitle }: { buttonTitle?: string }): JSX.Element => {
    const { filterGroup } = useValues(universalFiltersLogic)
    const { replaceGroupValue, removeGroupValue } = useActions(universalFiltersLogic)

    return (
        <div>
            <div className="inline-flex flex-col gap-2">
                {filterGroup.values.map((filterOrGroup, index) => {
                    return isUniversalGroupFilterLike(filterOrGroup) ? (
                        <UniversalFilters.Group key={index} index={index} group={filterOrGroup}>
                            <NestedFilterGroup />
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
                <div>
                    <UniversalFilters.AddFilterButton title={buttonTitle} type="secondary" size="xsmall" />
                </div>
            </div>
        </div>
    )
}

export const SingleTemplateVariable = ({
    variable,
    ...props
}: ReplayTemplateLogicPropsType & {
    variable: ReplayTemplateVariableType
}): JSX.Element | null => {
    const { setVariable, resetVariable } = useActions(sessionReplayTemplatesLogic(props))
    useMountedLogic(actionsModel)

    return variable.type === 'pageview' ? (
        <div>
            <LemonLabel info={variable.description}>{variable.name}</LemonLabel>
            <LemonInput
                placeholder={variable.value}
                value={variable.value}
                onChange={(e) =>
                    e ? setVariable({ ...variable, value: e }) : resetVariable({ ...variable, value: undefined })
                }
                size="small"
            />
        </div>
    ) : ['event', 'person-property'].includes(variable.type) ? (
        <div>
            <LemonLabel info={variable.description}>{variable.name}</LemonLabel>
            <UniversalFilters
                rootKey={`session-recordings-${variable.key}`}
                group={{
                    type: FilterLogicalOperator.And,
                    values: variable.filterGroup ? [variable.filterGroup] : [],
                }}
                taxonomicGroupTypes={
                    variable.type === 'event'
                        ? [TaxonomicFilterGroupType.Events, TaxonomicFilterGroupType.Actions]
                        : [TaxonomicFilterGroupType.PersonProperties]
                }
                onChange={(thisFilterGroup) => {
                    if (thisFilterGroup.values.length === 0) {
                        resetVariable({ ...variable, filterGroup: undefined })
                    } else {
                        setVariable({ ...variable, filterGroup: thisFilterGroup.values[0] })
                    }
                }}
            >
                <NestedFilterGroup buttonTitle={`Select ${variable.type === 'event' ? 'event' : 'person property'}`} />
            </UniversalFilters>
        </div>
    ) : null
}
