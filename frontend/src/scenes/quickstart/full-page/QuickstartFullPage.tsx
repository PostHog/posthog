import { useValues } from 'kea'

import { quickstartLogic } from '../quickstartLogic'
import { QuickstartModals } from '../shared/modals/QuickstartModals'
import { QuickstartHeader } from '../shared/QuickstartHeader'
import { QuickstartPageShell } from '../shared/QuickstartPageShell'
import { QuickstartToolsSections } from '../shared/QuickstartToolsSections'
import { CompanionSetupModal } from './CompanionSetupModal'
import { QuickstartGuidesSection } from './QuickstartGuidesSection'
import { QuickstartInstallationPrompt } from './QuickstartInstallationPrompt'

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
            <QuickstartModals installationComplete={installationComplete} />
            <CompanionSetupModal />
        </QuickstartPageShell>
    )
}
