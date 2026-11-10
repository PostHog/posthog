export function WizardInstallIntro({ description }: { description?: string } = {}): JSX.Element {
    return (
        <div className="space-y-2">
            <h2 className="text-xl font-bold">Set up with Wizard</h2>
            <p className="text-muted">
                {description ??
                    'The setup agent detects your framework, installs the SDK, and configures event capture.'}
            </p>
            <p className="text-muted text-xs">LLM inference is on us, no API key needed.</p>
        </div>
    )
}
