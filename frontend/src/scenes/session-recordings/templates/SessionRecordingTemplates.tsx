import { LemonButton, LemonCard, LemonInput, LemonLabel, Link } from '@posthog/lemon-ui'
import { useActions, useMountedLogic, useValues } from 'kea'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import UniversalFilters from 'lib/components/UniversalFilters/UniversalFilters'
import { universalFiltersLogic } from 'lib/components/UniversalFilters/universalFiltersLogic'
import { isUniversalGroupFilterLike } from 'lib/components/UniversalFilters/utils'

import { actionsModel } from '~/models/actionsModel'
import { FilterLogicalOperator, ReplayTemplateCategory, ReplayTemplateType, ReplayTemplateVariableType } from '~/types'

import { replayTemplates } from './availableTemplates'
import { sessionReplayTemplatesLogic } from './sessionRecordingTemplatesLogic'

const allCategories: ReplayTemplateCategory[] = replayTemplates
    .flatMap((template) => template.categories)
    .filter((category, index, self) => self.indexOf(category) === index)

const NestedFilterGroup = ({ rootKey, buttonTitle }: { rootKey: string; buttonTitle?: string }): JSX.Element => {
    const { filterGroup } = useValues(universalFiltersLogic)
    const { replaceGroupValue, removeGroupValue } = useActions(universalFiltersLogic)

    return (
        <div>
            <div className="inline-flex flex-col gap-2">
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
                <div>
                    <UniversalFilters.AddFilterButton title={buttonTitle} type="secondary" size="xsmall" />
                </div>
            </div>
        </div>
    )
}

const SingleTemplateVariable = ({
    variable,
    template,
}: {
    variable: ReplayTemplateVariableType
    template: ReplayTemplateType
}): JSX.Element | null => {
    const { setVariable } = useActions(sessionReplayTemplatesLogic({ template }))
    useMountedLogic(actionsModel)

    return variable.type === 'pageview' ? (
        <div>
            <LemonLabel info={variable.description}>{variable.name}</LemonLabel>
            <LemonInput
                placeholder={variable.value}
                onChange={(e) => setVariable({ ...variable, value: e })}
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
                    values: [],
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
                    setVariable({ ...variable, filterGroup: thisFilterGroup.values[0] })
                }}
            >
                <NestedFilterGroup
                    rootKey="session-recordings"
                    buttonTitle={`Select ${
                        variable.type === 'event' ? 'event' : variable.type === 'flag' ? 'flag' : 'person property'
                    }`}
                />
            </UniversalFilters>
        </div>
    ) : null
}

const TemplateVariables = ({ template }: { template: ReplayTemplateType }): JSX.Element => {
    const { navigate } = useActions(sessionReplayTemplatesLogic({ template }))
    const { variables, areAnyVariablesTouched } = useValues(sessionReplayTemplatesLogic({ template }))
    return (
        <div className="flex flex-col gap-2">
            {variables.map((variable) => (
                <SingleTemplateVariable key={variable.key} variable={variable} template={template} />
            ))}
            <div>
                <LemonButton
                    onClick={() => navigate()}
                    type="primary"
                    className="mt-2"
                    disabledReason={
                        !areAnyVariablesTouched ? 'Please set a value for at least one variable' : undefined
                    }
                >
                    Apply filters
                </LemonButton>
            </div>
        </div>
    )
}

const RecordingTemplateCard = ({ template }: { template: ReplayTemplateType }): JSX.Element => {
    const { showVariables, hideVariables, navigate } = useActions(sessionReplayTemplatesLogic({ template }))
    const { variablesVisible, editableVariables } = useValues(sessionReplayTemplatesLogic({ template }))

    return (
        <LemonCard
            className="w-80"
            onClick={() => {
                editableVariables.length > 0 ? showVariables() : navigate()
            }}
            closeable={variablesVisible}
            onClose={hideVariables}
            focused={variablesVisible}
        >
            <div className="flex flex-col gap-2">
                <h3>
                    <Link onClick={() => showVariables()} className="text-primary">
                        {template.name}
                    </Link>
                </h3>
                <p>{template.description}</p>
                {variablesVisible ? <TemplateVariables template={template} /> : null}
            </div>
        </LemonCard>
    )
}

const SessionRecordingTemplates = (): JSX.Element => {
    return (
        <div>
            <h2>Figure out what to watch</h2>
            <p>To get the most out of session replay, you just need to know where to start. </p>
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
                                <RecordingTemplateCard key={template.key} template={template} />
                            ))}
                    </div>
                </div>
            ))}
        </div>
    )
}

export default SessionRecordingTemplates
