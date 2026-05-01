import { useState } from 'react'

import { IconCopy, IconTerminal } from '@posthog/icons'

import { copyToClipboard } from 'lib/utils/copyToClipboard'

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

const WIZARD_FLASH_STYLE: React.CSSProperties = {
    ...WIZARD_GRADIENT_STYLE,
    color: '#36C46F',
    backgroundImage: 'none',
    WebkitBackgroundClip: 'unset',
    backgroundClip: 'unset',
    animation: 'wizard-copied-flash 1500ms ease-out forwards',
    position: 'absolute',
    inset: 0,
    pointerEvents: 'none',
}

const WIZARD_HOG_URL = 'https://res.cloudinary.com/dmukukwp6/image/upload/wizard_3f8bb7a240.png'

export function WizardCommandBlock(): JSX.Element {
    const { wizardCommand, isCloudOrDev } = useWizardCommand()
    const [copyKey, setCopyKey] = useState(0)

    // The `npx @posthog/wizard` CLI only targets cloud (US/EU) and dev instances —
    // self-hosted deployments have no preconfigured endpoint, so we hide the block
    // entirely rather than show a command that can't work. Matches SetupWizardBanner.
    if (!isCloudOrDev) {
        return <></>
    }

    const handleCopy = (): void => {
        void copyToClipboard(wizardCommand, 'Wizard command')
        setCopyKey((k) => k + 1)
    }

    return (
        <div className="flex flex-col gap-3">
            {/* Inject keyframe animations */}
            <style>{`
                @keyframes wizard-gradient-scroll {
                    0% { background-position-x: 0%; }
                    100% { background-position-x: 200%; }
                }
                @keyframes wizard-copied-flash {
                    0%, 50% { opacity: 1; }
                    100% { opacity: 0; }
                }
                @keyframes wizard-copy-bounce {
                    0% { transform: scale(1); }
                    15% { transform: scale(0.96); }
                    40% { transform: scale(1.03); }
                    70% { transform: scale(0.99); }
                    100% { transform: scale(1); }
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
                    key={`hog-${copyKey}`}
                    src={WIZARD_HOG_URL}
                    alt="PostHog wizard hedgehog"
                    className="w-28 h-28 hidden sm:block shrink-0 self-center"
                    style={copyKey > 0 ? { animation: 'wizard-hog-cast 500ms ease-out' } : undefined}
                />
                <div className="flex-1 flex flex-col gap-3">
                    <button
                        onClick={handleCopy}
                        key={`btn-${copyKey}`}
                        className="group inline-flex items-center gap-2 bg-bg-light border border-border font-mono text-sm px-4 py-3 rounded-lg cursor-pointer hover:border-primary transition-colors w-fit"
                        style={copyKey > 0 ? { animation: 'wizard-copy-bounce 400ms ease-out' } : undefined}
                    >
                        <IconTerminal className="size-4 text-muted" />
                        <span className="relative">
                            <code style={WIZARD_GRADIENT_STYLE} className="!bg-transparent !p-0 !border-0 select-all">
                                {wizardCommand}
                            </code>
                            {copyKey > 0 && (
                                <code
                                    key={copyKey}
                                    style={WIZARD_FLASH_STYLE}
                                    className="!bg-transparent !p-0 !border-0"
                                    aria-hidden="true"
                                >
                                    {wizardCommand}
                                </code>
                            )}
                        </span>
                        <IconCopy className="size-4 text-muted group-hover:text-primary" />
                    </button>

                    <p className="text-xs text-muted mb-0">
                        Auto-detects your framework, installs the SDK, and sets up event capture.
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
