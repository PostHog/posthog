/**
 * `unified` framing is used when both run modes are offered (the cloud experiment):
 * it talks about the wizard, not a specific command. Without it we keep the original
 * command-centric copy so the control arm is unchanged.
 */
export function WizardInstallIntro({ unified = false }: { unified?: boolean }): JSX.Element {
    if (unified) {
        return (
            <div className="text-center max-w-xl mx-auto space-y-3">
                <h2 className="text-2xl font-bold">Let the wizard install PostHog for you</h2>
                <p className="text-muted">
                    It drops in the SDK and wires up event capture, so you can skip the setup and get back to building.
                </p>
                <p className="text-muted text-xs">LLM inference is on us, no API key needed.</p>
            </div>
        )
    }

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
