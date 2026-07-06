export function WizardInstallIntro(): JSX.Element {
    return (
        <div className="text-center max-w-xl mx-auto space-y-3">
            <h2 className="text-2xl font-bold">Skip the install. Get 10–20 minutes back.</h2>
            <p className="text-muted">
                Run this command from your project&apos;s root directory. The wizard detects your framework, installs
                the right SDK, configures your environment variables, and wires up event capture automatically.
            </p>
            <p className="text-muted text-xs">LLM inference is on us, no API key needed.</p>
        </div>
    )
}
