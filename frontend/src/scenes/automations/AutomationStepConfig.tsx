import { LemonButton, LemonDivider, LemonLabel } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { IconClose } from 'lib/lemon-ui/icons'
import { ActionFilter } from 'scenes/insights/filters/ActionFilter/ActionFilter'
import { FilterType, InsightType } from '~/types'
import './AutomationStepConfig.scss'
import { automationStepConfigLogic, kindToConfig } from './automationStepConfigLogic'
import { AnyAutomationStep, AutomationStepCategory } from './schema'

export function EventSentConfig(): JSX.Element {
    const { activeStep } = useValues(automationStepConfigLogic)
    const { updateActiveStep } = useActions(automationStepConfigLogic)

    return (
        <div className="mb-6">
            <div className="mb-2">
                <LemonLabel>Event</LemonLabel>
                {/* <p className="text-sm text-muted">{variable.description}</p> */}
            </div>
            <div>
                <ActionFilter
                    filters={{
                        insight: InsightType.TRENDS,
                        events: activeStep.filters,
                    }}
                    setFilters={(filters: FilterType) => {
                        updateActiveStep(activeStep.id, { filters: filters.events })
                    }}
                    typeKey={'automation_step_event_sent_config'}
                    buttonCopy={''}
                    hideDeleteBtn={true}
                    hideRename={true}
                    hideDuplicate={true}
                    entitiesLimit={1}
                />
            </div>
        </div>
    )
}

export function AutomationStepChooser(): JSX.Element {
    const { setActiveStepId } = useActions(automationStepConfigLogic)
    const { stepOptions } = useValues(automationStepConfigLogic)

    return (
        <>
            <h2>New step</h2>
            <LemonDivider />
            {Object.values(AutomationStepCategory).map((category: AutomationStepCategory) => (
                <div key={category}>
                    <h3>{category}</h3>
                    <div className="StepChooser mb-4">
                        {Object.values(stepOptions)
                            .filter((option: AnyAutomationStep) => option.category === category)
                            .map((option: AnyAutomationStep, key: number) => (
                                <LemonButton
                                    type="secondary"
                                    icon={kindToConfig[option.id].icon}
                                    key={key}
                                    onClick={() => setActiveStepId(option.id)}
                                >
                                    {kindToConfig[option.id].label}
                                </LemonButton>
                            ))}
                    </div>
                    <LemonDivider />
                </div>
            ))}
        </>
    )
}

export function AutomationStepForm(): JSX.Element {
    const { activeStep, activeStepConfig } = useValues(automationStepConfigLogic)
    if (!activeStep) {
        return <h2>Error loading step</h2>
    }
    return (
        <>
            <h2>New step: {activeStepConfig.label}</h2>
            <LemonDivider />
            {activeStepConfig.configComponent}
            <LemonButton type="primary" onClick={() => console.log('Saving', activeStep)}>
                Save
            </LemonButton>
        </>
    )
}

export function AutomationStepConfig(): JSX.Element {
    const { activeStepId } = useValues(automationStepConfigLogic)
    const { closeStepConfig } = useActions(automationStepConfigLogic)

    return (
        <div className="w-full m-4 p-8 border bg-white AutomationStepConfig relative">
            <LemonButton
                icon={<IconClose />}
                size="small"
                status="stealth"
                onClick={closeStepConfig}
                aria-label="close"
                className="closebutton"
            />
            {activeStepId ? <AutomationStepForm /> : <AutomationStepChooser />}
        </div>
    )
}
