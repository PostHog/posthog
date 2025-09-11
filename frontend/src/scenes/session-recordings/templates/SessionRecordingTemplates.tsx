import { useActions, useMountedLogic, useValues } from 'kea'

import { LemonButton, LemonCard, LemonInput, LemonLabel, Link } from '@posthog/lemon-ui'

import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import UniversalFilters from 'lib/components/UniversalFilters/UniversalFilters'
import { universalFiltersLogic } from 'lib/components/UniversalFilters/universalFiltersLogic'
import { isUniversalGroupFilterLike } from 'lib/components/UniversalFilters/utils'
import { ReplayActiveScreensTable } from 'scenes/session-recordings/components/ReplayActiveScreensTable'

import { actionsModel } from '~/models/actionsModel'
import {
    FeaturePropertyFilter,
    FilterLogicalOperator,
    ReplayTemplateCategory,
    ReplayTemplateType,
    ReplayTemplateVariableType,
} from '~/types'

import { ReplayActiveHoursHeatMap } from '../components/ReplayActiveHoursHeatMap'
import { ReplayActiveUsersTable } from '../components/ReplayActiveUsersTable'
import { replayTemplates } from './availableTemplates'
import { sessionReplayTemplatesLogic } from './sessionRecordingTemplatesLogic'

interface RecordingTemplateCardProps {
    template: ReplayTemplateType
    category: ReplayTemplateCategory
}

const allCategories: ReplayTemplateCategory[] = replayTemplates
    .flatMap((template) => template.categories)
    .filter((category, index, self) => self.indexOf(category) === index)

const NestedFilterGroup = ({ buttonTitle, selectOne }: { buttonTitle?: string; selectOne?: boolean }): JSX.Element => {
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
                {!selectOne || (selectOne && filterGroup.values.length === 0) ? (
                    <div>
                        <UniversalFilters.AddFilterButton title={buttonTitle} type="secondary" size="xsmall" />
                    </div>
                ) : null}
            </div>
        </div>
    )
}

const SingleTemplateVariable = ({
    variable,
    ...props
}: RecordingTemplateCardProps & {
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
    ) : ['event', 'flag', 'person-property'].includes(variable.type) ? (
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
                        : variable.type === 'flag'
                          ? [TaxonomicFilterGroupType.FeatureFlags]
                          : variable.type === 'person-property'
                            ? [TaxonomicFilterGroupType.PersonProperties]
                            : []
                }
                onChange={(thisFilterGroup) => {
                    if (thisFilterGroup.values.length === 0) {
                        resetVariable({ ...variable, filterGroup: undefined })
                    } else if (variable.type === 'flag') {
                        setVariable({ ...variable, value: (thisFilterGroup.values[0] as FeaturePropertyFilter).key })
                    } else {
                        setVariable({ ...variable, filterGroup: thisFilterGroup.values[0] })
                    }
                }}
            >
                <NestedFilterGroup
                    buttonTitle={`Select ${
                        variable.type === 'event' ? 'event' : variable.type === 'flag' ? 'flag' : 'person property'
                    }`}
                    selectOne={variable.type == 'flag'}
                />
            </UniversalFilters>
        </div>
    ) : null
}

const TemplateVariables = (props: RecordingTemplateCardProps): JSX.Element => {
    const { navigate } = useActions(sessionReplayTemplatesLogic(props))
    const { variables, canApplyFilters } = useValues(sessionReplayTemplatesLogic(props))
    return (
        <div className="flex flex-col gap-2">
            {variables
                .filter((v) => !v.noTouch)
                .map((variable) => (
                    <SingleTemplateVariable key={variable.key} variable={variable} {...props} />
                ))}
            <div>
                <LemonButton
                    onClick={() => navigate()}
                    type="primary"
                    className="mt-2"
                    disabledReason={!canApplyFilters ? 'Please set a value for at least one variable' : undefined}
                >
                    Apply filters
                </LemonButton>
            </div>
        </div>
    )
}

const RecordingTemplateCard = (props: RecordingTemplateCardProps): JSX.Element => {
    const { showVariables, hideVariables } = useActions(sessionReplayTemplatesLogic(props))
    const { variablesVisible } = useValues(sessionReplayTemplatesLogic(props))

    return (
        <LemonCard
            className="w-80"
            onClick={() => {
                showVariables()
            }}
            closeable={variablesVisible}
            onClose={hideVariables}
            focused={variablesVisible}
            data-attr="session-replay-template"
            data-ph-capture-attribute-category={props.category}
            data-ph-capture-attribute-template={props.template.key}
        >
            <div className="flex flex-col gap-2">
                <div className="flex items-center gap-2">
                    {props.template.icon && (
                        <div className="bg-surface-primary rounded p-2 w-8 h-8 flex items-center justify-center">
                            {props.template.icon}
                        </div>
                    )}
                    <h3 className="mb-0">
                        <Link onClick={() => showVariables()} className="text-accent">
                            {props.template.name}
                        </Link>
                    </h3>
                </div>
                <p>{props.template.description}</p>
                {variablesVisible ? <TemplateVariables {...props} /> : null}
            </div>
        </LemonCard>
    )
}

const SessionRecordingTemplates = (): JSX.Element => {
    return (
        <div>
            <p>To get the most out of session replay, you just need to know where to start. </p>
            <div className="flex flex-col gap-2 w-full">
                <div className="flex flex-row gap-2 w-full">
                    <ReplayActiveUsersTable />
                    <ReplayActiveScreensTable />
                </div>
                <ReplayActiveHoursHeatMap />
            </div>
            <h2 className="mt-4">Filter templates</h2>
            <p>
                Use our templates to find a focus area, then watch the filtered replays to see where users struggle,
                what could be made more clear, and other ways to improve.
            </p>
            {allCategories.map((category) => (
                <div key={`replay-template-category-${category}`} className="mb-6">
                    <h2>{category}</h2>
                    <div className="flex flex-wrap gap-2">
                        {replayTemplates
                            .filter((template) => template.categories.includes(category))
                            .map((template) => (
                                <RecordingTemplateCard key={template.key} template={template} category={category} />
                            ))}
                    </div>
                </div>
            ))}
        </div>
    )
}

export default SessionRecordingTemplates
