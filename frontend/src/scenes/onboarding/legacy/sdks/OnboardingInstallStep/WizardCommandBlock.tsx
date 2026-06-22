import './WizardCommandBlock.scss'

import { ComponentType, useState } from 'react'

import { CommandBlock } from 'lib/components/CommandBlock/CommandBlock'
import { cn } from 'lib/utils/css-classes'
import { useWizardCommand } from 'scenes/onboarding/shared/SetupWizardBanner'

import androidImage from '../logos/android.svg'
import angularImage from '../logos/angular.svg'
import { AstroLogo } from '../logos/AstroLogo'
import djangoImage from '../logos/django.svg'
import flaskImage from '../logos/flask.svg'
import { IOSLogo } from '../logos/IOSLogo'
import laravelImage from '../logos/laravel.svg'
import nextjsImage from '../logos/nextjs.svg'
import nuxtImage from '../logos/nuxt.svg'
import pythonImage from '../logos/python.svg'
import railsImage from '../logos/rails.svg'
import reactImage from '../logos/react.svg'
import { ReactRouterLogo } from '../logos/ReactRouterLogo'
import svelteImage from '../logos/svelte.svg'
import vueImage from '../logos/vue.svg'

// Supported wizard frameworks for display
const WIZARD_FRAMEWORKS: { name: string; icon: string | ComponentType }[] = [
    { name: 'Next.js', icon: nextjsImage },
    { name: 'React', icon: reactImage },
    { name: 'Angular', icon: angularImage },
    { name: 'Vue', icon: vueImage },
    { name: 'Nuxt', icon: nuxtImage },
    { name: 'Astro', icon: AstroLogo },
    { name: 'SvelteKit', icon: svelteImage },
    { name: 'Django', icon: djangoImage },
    { name: 'Flask', icon: flaskImage },
    { name: 'Laravel', icon: laravelImage },
    { name: 'React Native', icon: reactImage },
    { name: 'iOS', icon: IOSLogo },
    { name: 'Android', icon: androidImage },
    { name: 'Ruby on Rails', icon: railsImage },
    { name: 'React Router', icon: ReactRouterLogo },
    { name: 'Python', icon: pythonImage },
]

export const WIZARD_HOG_URL = 'https://res.cloudinary.com/dmukukwp6/image/upload/wizard_3f8bb7a240.png'

export function WizardCommandBlock(): JSX.Element {
    const { wizardCommand, isCloudOrDev } = useWizardCommand()
    const [castKey, setCastKey] = useState(0)

    // The `npx @posthog/wizard` CLI only targets cloud (US/EU) and dev instances —
    // self-hosted deployments have no preconfigured endpoint, so we hide the block
    // entirely rather than show a command that can't work. Matches SetupWizardBanner.
    if (!isCloudOrDev) {
        return <></>
    }

    return (
        <div className="flex flex-col gap-3">
            <div className="flex gap-6">
                <img
                    key={`hog-${castKey}`}
                    src={WIZARD_HOG_URL}
                    alt="PostHog wizard hedgehog"
                    className={cn(
                        'w-28 h-28 hidden sm:block shrink-0 self-center',
                        castKey > 0 && 'WizardCommandBlock__hogCast'
                    )}
                />
                <div className="flex-1 flex flex-col gap-3">
                    <CommandBlock
                        command={wizardCommand}
                        copyLabel="Wizard command"
                        ariaLabel="Copy wizard command"
                        size="md"
                        decoration="rainbow"
                        className="bg-bg-light border border-border hover:border-primary"
                        onCopy={(key) => setCastKey(key)}
                    />

                    <p className="text-xs text-muted mb-0">
                        Auto-detects your framework, installs the SDK, and sets up event capture.
                    </p>

                    <div className="flex flex-wrap gap-1.5 items-center">
                        <span className="text-xs text-muted">Supports:</span>
                        {WIZARD_FRAMEWORKS.map((fw) => (
                            <span
                                key={fw.name}
                                className="inline-flex items-center gap-1 text-xs text-muted bg-bg-light border border-border rounded px-1.5 py-0.5"
                            >
                                {typeof fw.icon === 'string' ? (
                                    <img src={fw.icon} alt="" className="w-3 h-3 shrink-0" />
                                ) : (
                                    <span className="inline-flex w-3 h-3 shrink-0 [&_svg]:!w-3 [&_svg]:!h-3">
                                        <fw.icon />
                                    </span>
                                )}
                                {fw.name}
                            </span>
                        ))}
                    </div>
                </div>
            </div>
        </div>
    )
}
