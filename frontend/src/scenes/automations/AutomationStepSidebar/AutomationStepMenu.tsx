import { LemonButton, LemonDivider } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { automationLogic } from '../automationLogic'
import './AutomationStepConfig.scss'
import { automationStepConfigLogic, kindToConfig } from './automationStepConfigLogic'
import { AnyAutomationStep, AutomationStepCategory, AutomationStepKind } from '../schema'
import { automationStepMenuLogic } from './automationStepMenuLogic'
import { AutomationStepSidebar } from './AutomationStepSidebar'
import { uuid } from 'lib/utils'

type AnyAutomationStepWithCategory = AnyAutomationStep & { category: AutomationStepCategory }

const stepOptions: AnyAutomationStepWithCategory[] = [
    {
        kind: AutomationStepKind.EventSource,
        category: AutomationStepCategory.Source,
        id: 'new',
        filters: [],
    },
    // { kind: AutomationStepKind.ActionSource, category: AutomationStepCategory.Source },
    // { kind: AutomationStepKind.CronJobSource, category: AutomationStepCategory.Source },
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
    {
        kind: AutomationStepKind.WebhookDestination,
        category: AutomationStepCategory.Destination,
        id: 'new',
    },
    { kind: AutomationStepKind.SlackDestination, category: AutomationStepCategory.Destination, id: 'new' },
    // { kind: AutomationStepKind.ZapierDestination, category: AutomationStepCategory.Destination },
    // { kind: AutomationStepKind.EmailDestination, category: AutomationStepCategory.Destination },
    // {
    //     kind: AutomationStepKind.InAppMessageDestination,
    //     category: AutomationStepCategory.Destination,
    // },
]

type AutomationStepMenuProps = {
    isOpen: boolean
}

export function AutomationStepMenu({ isOpen }: AutomationStepMenuProps): JSX.Element | null {
    const { closeMenu } = useActions(automationStepMenuLogic)
    const { setActiveStepId } = useActions(automationStepConfigLogic)
    const { addStep } = useActions(automationLogic)
    const { automation } = useValues(automationLogic)

    if (!isOpen) {
        return null
    }

    return (
        <AutomationStepSidebar onClose={closeMenu}>
            <h2>New step</h2>
            <LemonDivider className="mb-4" />
            {Object.values(AutomationStepCategory).map((category: AutomationStepCategory) => (
                <div key={category}>
                    <h3>{category}</h3>
                    <div className="StepChooser mb-4">
                        {Object.values(stepOptions)
                            .filter((option) => option.category === category)
                            .map((option, key: number) => (
                                <LemonButton
                                    type="secondary"
                                    icon={kindToConfig[option.kind].icon}
                                    key={key}
                                    onClick={() => {
                                        const id = uuid()
                                        addStep({ ...option, id })
                                        closeMenu()
                                        setActiveStepId(id)
                                    }}
                                    disabledReason={
                                        automation.steps.length > 0 && option.category === AutomationStepCategory.Source
                                            ? 'You can only have one event source'
                                            : automation.steps.length === 0 &&
                                              option.category !== AutomationStepCategory.Source
                                            ? 'You must start with an event source'
                                            : undefined
                                    }
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
