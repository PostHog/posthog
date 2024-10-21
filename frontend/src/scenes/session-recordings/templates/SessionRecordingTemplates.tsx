import { LemonButton, LemonCard, LemonInput, LemonLabel, Link } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'

import { ReplayTemplateCategory, ReplayTemplateType, ReplayTemplateVariableType } from '~/types'

import { replayTemplates, sessionReplayTemplatesLogic } from './sessionRecordingTemplatesLogic'

const allCategories: ReplayTemplateCategory[] = replayTemplates
    .flatMap((template) => template.categories)
    .filter((category, index, self) => self.indexOf(category) === index)

const SingleTemplateVariable = ({
    variable,
    template,
}: {
    variable: ReplayTemplateVariableType
    template: ReplayTemplateType
}): JSX.Element | null => {
    const { setVariable } = useActions(sessionReplayTemplatesLogic({ template }))
    return ['event', 'pageview'].includes(variable.type) ? (
        <div>
            <LemonLabel info={variable.description}>{variable.name}</LemonLabel>
            <LemonInput
                placeholder={variable.value}
                onChange={(e) => setVariable({ ...variable, value: e })}
                size="small"
            />
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
    const { showVariables, hideVariables } = useActions(sessionReplayTemplatesLogic({ template }))
    const { variablesVisible } = useValues(sessionReplayTemplatesLogic({ template }))
    return (
        <LemonCard
            className="w-80"
            onClick={() => {
                showVariables()
            }}
            closeable={variablesVisible}
            // TODO IN THIS PR: For some reason, this gets called with the correct template, but the variables don't hide.
            // The change in selector value isn't triggering a refresh of the LemonCard component.
            onClose={() => hideVariables()}
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
