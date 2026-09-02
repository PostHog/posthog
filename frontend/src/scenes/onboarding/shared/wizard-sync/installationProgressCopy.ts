import { InstallationMode, InstallationProgress } from './installationProgressLogic'

/**
 * The header copy for a run, one branch per phase. The self-driving program sets up scouts and
 * signal sources rather than installing an SDK, so the "what just happened" copy has to follow the
 * program — wording matches the CLI's own outro so the terminal and the browser tell the same story.
 */
export function syncCopy({
    progress,
    mode,
    selfDriving,
    prReady,
}: {
    progress: InstallationProgress
    mode?: InstallationMode
    selfDriving: boolean
    /** A PR exists while the run is still going — surfaced as ready rather than "setting up". */
    prReady: boolean
}): { headline: string; subtitle: string } {
    const { phase, error, prUrl, prMerged } = progress

    if (phase === 'completed') {
        const headline = selfDriving ? 'Self-driving is on' : 'PostHog is wired up'
        if (prUrl) {
            return {
                headline,
                subtitle: prMerged
                    ? 'Your pull request is merged. Deploy the changes and data starts flowing.'
                    : 'Review and merge the pull request, then deploy. Data starts flowing the moment it ships.',
            }
        }
        if (selfDriving) {
            return {
                headline,
                subtitle: 'Your scouts are watching. First findings hit your inbox within about 30 minutes.',
            }
        }
        return {
            headline,
            subtitle: mode === 'local' ? 'The wizard finished its work on your machine.' : "You're all set.",
        }
    }

    if (phase === 'error') {
        return { headline: error?.title ?? "Setup didn't finish", subtitle: "We couldn't finish the setup." }
    }

    if (prReady) {
        return prMerged
            ? {
                  headline: 'Pull request merged',
                  subtitle: 'Deploy the changes and data starts flowing. The run will wrap up on its own.',
              }
            : {
                  headline: 'Pull request ready',
                  subtitle: "Review it whenever you like; we'll keep CI green in the meantime.",
              }
    }

    const headline = selfDriving ? 'Setting up self-driving' : 'Setting up PostHog'
    if (phase === 'connecting') {
        return { headline, subtitle: (mode && CONNECTING_SUBTITLE[mode]) ?? 'Getting things ready…' }
    }
    if (phase === 'idle') {
        return { headline, subtitle: 'Not hearing back from this run right now. You can dismiss it and start over.' }
    }
    return { headline, subtitle: 'Working on it. Feel free to keep going.' }
}

const CONNECTING_SUBTITLE: Record<InstallationMode, string> = {
    cloud: 'Firing up a sandbox for your repo. The wizard takes it from there.',
    local: 'Waiting for the wizard in your terminal to check in.',
}

// What's about to happen, shown as pending timeline rows while the stream connects. Same geometry
// (and, for cloud, the same gerund phrasing) as the streamed steps that replace them, so the swap
// reads as the plan lighting up rather than the card rewriting itself.
export const UPCOMING_STEPS: Record<InstallationMode, string[]> = {
    cloud: ['Setting up sandbox', 'Cloning repository', 'Running setup wizard', 'Opening a pull request'],
    local: ['Detecting your framework', 'Installing the PostHog SDK', 'Wiring up event capture'],
}

// The self-driving program does different work, so previewing the SDK-install steps would promise
// the wrong thing while we wait for the run to report in.
export const SELF_DRIVING_UPCOMING_STEPS = ['Connecting GitHub', 'Choosing signal sources', 'Tailoring your scouts']
