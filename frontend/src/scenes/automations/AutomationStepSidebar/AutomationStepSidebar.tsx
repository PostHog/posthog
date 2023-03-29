import { LemonButton } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { IconClose } from 'lib/lemon-ui/icons'
import { automationStepConfigLogic } from './automationStepConfigLogic'
import { AutomationStepMenu } from './AutomationStepMenu'
import { AutomationStepConfig } from './AutomationStepConfig'

export function AutomationStepSidebar(): JSX.Element {
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
            {activeStepId ? <AutomationStepConfig /> : <AutomationStepMenu />}
        </div>
    )
}
