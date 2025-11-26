import { useActions, useValues } from 'kea'

import { LemonInput, LemonLabel, LemonSelect } from '@posthog/lemon-ui'

import { quickSurveyFormLogic } from 'scenes/surveys/quick-create/quickSurveyFormLogic'
import { FunnelContext, toSurveyEvent } from 'scenes/surveys/utils/opportunityDetection'

import { EventsNode } from '~/queries/schema/schema-general'

export function FunnelSequence({ steps }: { steps: FunnelContext['steps'] }): JSX.Element {
    const { selectedEvents, delaySeconds } = useValues(quickSurveyFormLogic)
    const { updateConditions, updateAppearance } = useActions(quickSurveyFormLogic)

    return (
        <div>
            <LemonLabel className="mb-2">When should the survey appear?</LemonLabel>
            <div className="flex flex-wrap items-center gap-2 text-sm">
                <span>User does</span>
                <LemonSelect
                    value={selectedEvents[0] || null}
                    onChange={(val) => {
                        const step = steps.find((s) => s.name === val) as EventsNode
                        updateConditions({
                            events: {
                                values: step ? [toSurveyEvent(step)] : [],
                            },
                        })
                    }}
                    options={steps.map((step, idx) => ({
                        value: step.name ?? idx.toString(),
                        label: step.custom_name ?? step.name ?? idx.toString(),
                    }))}
                    placeholder="select step"
                    size="small"
                />
                <span>, but not</span>
                <LemonSelect
                    value={selectedEvents[0] || null}
                    // value={cancelEvents[0] || null}
                    onChange={(val) => {
                        const step = steps.find((s) => s.name === val) as EventsNode
                        updateConditions({
                            events: {
                                values: step ? [toSurveyEvent(step)] : [],
                            },
                            // cancelEvents: {
                            //     values: step ? [toSurveyEvent(step)] : [],
                            // },
                        })
                    }}
                    options={steps.map((step, idx) => ({
                        value: step.name ?? idx.toString(),
                        label: step.custom_name ?? step.name ?? idx.toString(),
                    }))}
                    placeholder="select step"
                    size="small"
                />
                <span>within</span>
                <LemonInput
                    type="number"
                    min={1}
                    value={delaySeconds}
                    onChange={(val) => updateAppearance({ surveyPopupDelaySeconds: val })}
                    className="w-20"
                />
                <span>seconds</span>
            </div>
        </div>
    )
}
