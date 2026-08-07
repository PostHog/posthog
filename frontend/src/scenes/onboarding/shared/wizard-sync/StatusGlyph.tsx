import { IconCheckCircle, IconPullRequest, IconQuestion, IconWarning } from '@posthog/icons'
import { Spinner } from '@posthog/lemon-ui'

import { InstallationProgress } from './installationProgressLogic'

// Leading glyph for the prominent task line: it carries the run's tone (accent while working, green on
// success, red on failure). Shared by the collapsed card, the launcher, the dialog, and the inbox rail.
export function StatusGlyph({ progress }: { progress: InstallationProgress }): JSX.Element {
    if (progress.phase === 'completed') {
        return <IconCheckCircle className="text-success text-xl shrink-0" />
    }
    if (progress.phase === 'error') {
        return <IconWarning className="text-danger text-xl shrink-0" />
    }
    if (progress.prMerged) {
        return <IconPullRequest className="text-purple text-xl shrink-0" />
    }
    if (progress.pendingInput) {
        return <IconQuestion className="text-warning text-xl shrink-0" />
    }
    return <Spinner className="text-xl shrink-0 text-accent" textColored />
}
