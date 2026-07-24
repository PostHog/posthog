import { TaskGuidanceModal } from './TaskGuidanceModal'
import { ToolSetupModal } from './ToolSetupModal'

export function QuickstartModals({ installationComplete }: { installationComplete: boolean }): JSX.Element {
    return (
        <>
            <TaskGuidanceModal />
            <ToolSetupModal installationComplete={installationComplete} />
        </>
    )
}
