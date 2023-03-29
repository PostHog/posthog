import { LemonButton, LemonDivider, LemonLabel } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { IconClose } from 'lib/lemon-ui/icons'
import { ActionFilter } from 'scenes/insights/filters/ActionFilter/ActionFilter'
import { MathAvailability } from 'scenes/insights/filters/ActionFilter/ActionFilterRow/ActionFilterRow'
import { FilterType, InsightType } from '~/types'
import { automationLogic } from './automationLogic'
import './AutomationStepConfig.scss'
import { automationStepConfigLogic, kindToConfig } from './automationStepConfigLogic'
import { AnyAutomationStep, AutomationStepCategory } from './schema'

export function EventSentConfig(): JSX.Element {
    const { activeStep } = useValues(automationStepConfigLogic)
    const { updateActiveStep } = useActions(automationStepConfigLogic)

    return (
        <div className="mb-6">
            <div className="mb-2">
                <LemonLabel showOptional>Event filtering</LemonLabel>
                {/* <p className="text-sm text-muted">{variable.description}</p> */}
            </div>
            <div>
                <ActionFilter
                    filters={{
                        insight: InsightType.TRENDS,
                        events: activeStep.filters,
                        new_entity: activeStep.new_entity,
                    }}
                    setFilters={(filters: FilterType) => {
                        updateActiveStep(activeStep.id, { filters: filters.events, new_entity: filters.new_entity })
                    }}
                    typeKey={'automation_step_event_sent_config'}
                    buttonCopy={'Action or event filter'}
                    mathAvailability={MathAvailability.None}
                />
            </div>
            {/* TODO: add this back to enable CDP use case of filtering all properties */}
            {/* <div className="mb-2">
                <LemonLabel showOptional>Event properties</LemonLabel>
            </div>
            <div>
                <PropertyFilters
                    propertyFilters={[]}
                    onChange={() => {}}
                    pageKey={'pageKey'}
                    style={{ marginBottom: 0 }}
                    showNestedArrow
                    eventNames={[]}
                    taxonomicGroupTypes={[TaxonomicFilterGroupType.EventProperties]}
                />
            </div> */}
            <div className="mb-2">
                <LemonLabel showOptional>Person and cohort</LemonLabel>
                {/* <p className="text-sm text-muted">{variable.description}</p> */}
            </div>
            <div>
                <PropertyFilters
                    propertyFilters={[]}
                    onChange={() => {}}
                    pageKey={'pageKey'}
                    style={{ marginBottom: 0 }}
                    showNestedArrow
                    eventNames={[]}
                    taxonomicGroupTypes={[TaxonomicFilterGroupType.PersonProperties, TaxonomicFilterGroupType.Cohorts]}
                />
            </div>
        </div>
    )
}

export function AutomationStepChooser(): JSX.Element {
    const { setActiveStepId } = useActions(automationStepConfigLogic)
    const { stepOptions } = useValues(automationStepConfigLogic)
    const { updateStep } = useActions(automationLogic)

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
                                    icon={kindToConfig[option.kind].icon}
                                    key={key}
                                    onClick={() => {
                                        // const id = uuid()
                                        updateStep(option)
                                        setActiveStepId(option.id)
                                    }}
                                >
                                    {kindToConfig[option.kind].label}
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
    const { addStep } = useActions(automationLogic)
    if (!activeStep) {
        return <h2>Error loading step</h2>
    }
    return (
        <>
            <h2>New step: {activeStepConfig.label}</h2>
            <LemonDivider />
            {activeStepConfig.configComponent}
            <LemonButton
                type="primary"
                onClick={() => {
                    console.debug('Saving', activeStep)
                    addStep(activeStep)
                }}
            >
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
