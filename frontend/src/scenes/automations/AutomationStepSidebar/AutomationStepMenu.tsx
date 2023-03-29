import { LemonButton, LemonDivider } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { automationLogic } from '../automationLogic'
import './AutomationStepConfig.scss'
import { automationStepConfigLogic, kindToConfig } from './automationStepConfigLogic'
import { AnyAutomationStep, AutomationStepCategory } from '../schema'
import { automationStepMenuLogic } from './automationStepMenuLogic'
import { AutomationStepSidebar } from './AutomationStepSidebar'

export function AutomationStepMenu(): JSX.Element {
    const { closeMenu } = useActions(automationStepMenuLogic)
    const { setActiveStepId } = useActions(automationStepConfigLogic)
    const { stepOptions } = useValues(automationStepConfigLogic)
    const { updateStep } = useActions(automationLogic)

    return (
        <AutomationStepSidebar onClose={closeMenu}>
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
                                        console.debug('clicked', option)

                                        updateStep(option)
                                        closeMenu()
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
        </AutomationStepSidebar>
    )
}
