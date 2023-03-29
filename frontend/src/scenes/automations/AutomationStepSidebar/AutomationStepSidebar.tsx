import { LemonButton } from '@posthog/lemon-ui'
import { IconClose } from 'lib/lemon-ui/icons'

// export function AutomationStepSidebar(): JSX.Element {
//     const { activeStepId } = useValues(automationStepConfigLogic)
//     const { closeStepConfig } = useActions(automationStepConfigLogic)

//     return (
//         <div className="w-full m-4 p-8 border bg-white AutomationStepConfig relative">
//             <LemonButton
//                 icon={<IconClose />}
//                 size="small"
//                 status="stealth"
//                 onClick={closeStepConfig}
//                 aria-label="close"
//                 className="closebutton"
//             />
//             {activeStepId ? <AutomationStepConfig /> : <AutomationStepMenu />}
//         </div>
//     )
// }

type AutomationStepSidebarProps = {
    onClose: () => void
    children: React.ReactNode
}

export function AutomationStepSidebar({ onClose, children }: AutomationStepSidebarProps): JSX.Element {
    return (
        <div className="w-full m-4 p-8 border bg-white AutomationStepConfig relative">
            <LemonButton
                icon={<IconClose />}
                size="small"
                status="stealth"
                onClick={onClose}
                aria-label="close"
                className="closebutton"
            />
            {children}
        </div>
    )
}
