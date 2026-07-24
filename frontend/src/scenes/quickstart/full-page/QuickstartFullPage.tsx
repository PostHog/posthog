import { useValues } from 'kea'

import { quickstartLogic } from '../quickstartLogic'
import { ToolSetupModal } from '../shared/modals/ToolSetupModal'
import { QuickstartHeader } from '../shared/QuickstartHeader'
import { QuickstartPageShell } from '../shared/QuickstartPageShell'
import { CompanionSetupModal } from './CompanionSetupModal'
import { QuickstartGuidesSection } from './QuickstartGuidesSection'
import { QuickstartInstallationPrompt } from './QuickstartInstallationPrompt'
import { QuickstartToolsSections } from './QuickstartToolsSections'
import { TaskGuidanceModal } from './TaskGuidanceModal'

/** The test arm: the full homepage with tool cards, guides, companions, and publications. */
export function QuickstartFullPage(): JSX.Element {
    const { hasIngestedEvent: installationComplete } = useValues(quickstartLogic)

    return (
        <QuickstartPageShell>
            <QuickstartHeader
                installStatus={<QuickstartInstallationPrompt installationComplete={installationComplete} />}
            />
            <QuickstartToolsSections />
            <QuickstartGuidesSection />
            <TaskGuidanceModal />
            <ToolSetupModal installationComplete={installationComplete} />
            <CompanionSetupModal />
        </QuickstartPageShell>
    )
}
