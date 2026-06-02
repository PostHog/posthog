import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

/**
 * Intro copy above the wizard command block.
 *
 * Experiment: ONBOARDING_WIZARD_INSTALLATION_IMPROVED_COPY (#team-growth)
 *   control — original one-line tagline.
 *   test    — expanded copy: enumerates what the wizard does, where to run it,
 *             and surfaces that PostHog covers LLM inference (no API key).
 *
 * Flag lookup lives here so WizardInstallStep stays agnostic of the experiment.
 */
export function WizardInstallIntro(): JSX.Element {
    const isImprovedCopy = useFeatureFlag('ONBOARDING_WIZARD_INSTALLATION_IMPROVED_COPY', 'test')
    return isImprovedCopy ? <ImprovedIntro /> : <ControlIntro />
}

function ControlIntro(): JSX.Element {
    return (
        <div className="text-center max-w-lg mx-auto">
            <h2 className="text-2xl font-bold mb-2">Install PostHog with one command</h2>
            <p className="text-muted">
                Our AI wizard detects your framework, installs the right SDK, and configures event capture
                automatically.
            </p>
        </div>
    )
}

function ImprovedIntro(): JSX.Element {
    return (
        <div className="text-center max-w-xl mx-auto space-y-3">
            <h2 className="text-2xl font-bold">Skip the install. Get 10–20 minutes back.</h2>
            <p className="text-muted">
                Run this command from your project&apos;s root directory. The wizard detects your framework, installs
                the right SDK, configures your environment variables, and wires up event capture automatically.
            </p>
            <p className="text-muted text-xs">LLM inference is on us — no API key needed.</p>
        </div>
    )
}
