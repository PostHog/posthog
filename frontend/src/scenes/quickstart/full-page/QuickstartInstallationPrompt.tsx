import { QuickstartWizardProgress } from '../shared/QuickstartWizardProgress'
import { QuickstartInstallationLink } from './QuickstartInstallationLink'
import { QuickstartInstallationProgress } from './QuickstartInstallationProgress'

export function QuickstartInstallationPrompt({
    installationComplete,
}: {
    installationComplete: boolean
}): JSX.Element | null {
    return (
        <QuickstartWizardProgress fallback={installationComplete ? null : <QuickstartInstallationLink />}>
            {(progress) => <QuickstartInstallationProgress progress={progress} />}
        </QuickstartWizardProgress>
    )
}
