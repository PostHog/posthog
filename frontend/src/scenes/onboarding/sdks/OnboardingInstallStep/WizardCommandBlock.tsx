import { useValues } from 'kea'
import posthog from 'posthog-js'
import { useEffect, useState } from 'react'

import { IconCheck, IconCopy, IconTerminal } from '@posthog/icons'

import { copyToClipboard } from 'lib/utils/copyToClipboard'

import { onboardingLogic } from '../../onboardingLogic'
import { useWizardCommand } from '../sdk-install-instructions/components/SetupWizardBanner'

// Supported wizard frameworks for display
const WIZARD_FRAMEWORKS = [
    'Next.js',
    'React',
    'Angular',
    'Vue',
    'Nuxt',
    'Astro',
    'SvelteKit',
    'Django',
    'Flask',
    'Laravel',
    'React Native',
    'iOS',
    'Android',
    'Ruby on Rails',
    'React Router',
    'Python',
]

const WIZARD_GRADIENT_STYLE: React.CSSProperties = {
    color: 'transparent',
    WebkitBackgroundClip: 'text',
    backgroundClip: 'text',
    backgroundImage:
        'linear-gradient(90deg, #0143cb 0%, #2b6ff4 24%, #d23401 47%, #ff651f 66%, #fba000 83%, #0143cb 100%)',
    backgroundSize: '200% 100%',
    animation: 'wizard-gradient-scroll 3s linear infinite',
}

const WIZARD_HOG_URL = 'https://res.cloudinary.com/dmukukwp6/image/upload/wizard_3f8bb7a240.png'

// Long enough for the user to register the state change after a click — short
// flashes (~400ms) read as a glitch rather than confirmation. See signal report
// 2026-04 on the wizard install button being perceived as unresponsive.
const COPIED_STATE_MS = 2500

export function WizardCommandBlock(): JSX.Element {
    const { wizardCommand, isCloudOrDev } = useWizardCommand()
    const { productKey } = useValues(onboardingLogic)
    const [copied, setCopied] = useState(false)

    // Reset the "Copied!" affordance after the persistent confirmation window so
    // the button reverts to its idle state and can be clicked again.
    useEffect(() => {
        if (!copied) {
            return
        }
        const timer = setTimeout(() => setCopied(false), COPIED_STATE_MS)
        return () => clearTimeout(timer)
    }, [copied])

    // The `npx @posthog/wizard` CLI only targets cloud (US/EU) and dev instances —
    // self-hosted deployments have no preconfigured endpoint, so we hide the block
    // entirely rather than show a command that can't work. Matches SetupWizardBanner.
    if (!isCloudOrDev) {
        return <></>
    }

    const handleCopy = async (): Promise<void> => {
        const success = await copyToClipboard(wizardCommand, 'Wizard command')
        if (success) {
            setCopied(true)
            posthog.capture('onboarding wizard command copied', { product_key: productKey })
        }
    }

    return (
        <div className="flex flex-col gap-3">
            {/* Inject keyframe animations */}
            <style>{`
                @keyframes wizard-gradient-scroll {
                    0% { background-position-x: 0%; }
                    100% { background-position-x: 200%; }
                }
                @keyframes wizard-hog-cast {
                    0% { transform: rotate(0deg); }
                    20% { transform: rotate(-8deg); }
                    50% { transform: rotate(5deg); }
                    80% { transform: rotate(-2deg); }
                    100% { transform: rotate(0deg); }
                }
            `}</style>

            <div className="flex gap-6">
                <img
                    src={WIZARD_HOG_URL}
                    alt="PostHog wizard hedgehog"
                    className="w-28 h-28 hidden sm:block shrink-0 self-center"
                    style={copied ? { animation: 'wizard-hog-cast 500ms ease-out' } : undefined}
                />
                <div className="flex-1 flex flex-col gap-3">
                    <button
                        onClick={() => void handleCopy()}
                        aria-label={copied ? 'Command copied to clipboard' : 'Click to copy install command'}
                        className="group inline-flex items-center gap-2 bg-bg-light border border-border font-mono text-sm px-4 py-3 rounded-lg cursor-pointer hover:border-primary transition-colors w-fit"
                        data-attr="wizard-command-copy"
                    >
                        <IconTerminal className="size-4 text-muted" />
                        <code style={WIZARD_GRADIENT_STYLE} className="!bg-transparent !p-0 !border-0 select-all">
                            {wizardCommand}
                        </code>
                        {copied ? (
                            <span className="inline-flex items-center gap-1 text-xs font-sans font-medium text-success">
                                <IconCheck className="size-4" />
                                Copied!
                            </span>
                        ) : (
                            <span className="inline-flex items-center gap-1 text-xs font-sans text-muted group-hover:text-primary">
                                <IconCopy className="size-4" />
                                Click to copy
                            </span>
                        )}
                    </button>

                    <p className="text-xs text-muted mb-0">
                        Copy this command and run it in your terminal. The wizard auto-detects your framework, installs
                        the SDK, and sets up event capture.
                    </p>

                    <div className="flex flex-wrap gap-1.5">
                        <span className="text-xs text-muted">Supports:</span>
                        {WIZARD_FRAMEWORKS.map((fw) => (
                            <span
                                key={fw}
                                className="text-xs text-muted bg-bg-light border border-border rounded px-1.5 py-0.5"
                            >
                                {fw}
                            </span>
                        ))}
                    </div>
                </div>
            </div>
        </div>
    )
}
