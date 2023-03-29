import { LemonButton, LemonDivider } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { automationLogic } from '../automationLogic'
import './AutomationStepConfig.scss'
import { automationStepConfigLogic, kindToConfig } from './automationStepConfigLogic'
import { AnyAutomationStep, AutomationStepCategory, AutomationStepKind } from '../schema'
import { automationStepMenuLogic } from './automationStepMenuLogic'
import { AutomationStepSidebar } from './AutomationStepSidebar'
import { uuid } from 'lib/utils'

const stepOptions: AnyAutomationStep[] = [
    {
        kind: AutomationStepKind.EventSource,
        id: 'new',
        category: AutomationStepCategory.Source,
        filters: [],
    },
    // { kind: AutomationStepKind.ActionSource, category: AutomationStepCategory.Source },
    // { kind: AutomationStepKind.PauseForLogic, category: AutomationStepCategory.Logic },
    // { kind: AutomationStepKind.PauseUntilLogic, category: AutomationStepCategory.Logic },
    // {
    //     kind: AutomationStepKind.GithubIssueDestination,
    //     category: AutomationStepCategory.Destination,
    // },
    // {
    //     kind: AutomationStepKind.UserPropertyDestination,
    //     category: AutomationStepCategory.Destination,
    // },
    // { kind: AutomationStepKind.CohortDestination, category: AutomationStepCategory.Destination },
    // {
    //     kind: AutomationStepKind.FeatureFlagDestination,
    //     category: AutomationStepCategory.Destination,
    // },
    { kind: AutomationStepKind.WebhookDestination, id: 'new', category: AutomationStepCategory.Destination },
    // { kind: AutomationStepKind.SlackDestination, category: AutomationStepCategory.Destination },
    // { kind: AutomationStepKind.ZapierDestination, category: AutomationStepCategory.Destination },
    // { kind: AutomationStepKind.EmailDestination, category: AutomationStepCategory.Destination },
    // {
    //     kind: AutomationStepKind.InAppMessageDestination,
    //     category: AutomationStepCategory.Destination,
    // },
]

export function AutomationStepMenu(): JSX.Element {
    const { closeMenu } = useActions(automationStepMenuLogic)
    const { setActiveStepId } = useActions(automationStepConfigLogic)
    const { addStep } = useActions(automationLogic)

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

                                        addStep({ ...option, id: uuid() })
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
