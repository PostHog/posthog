import './WizardModeShell.scss'

import type { ComponentType, ReactNode } from 'react'

import { cn } from 'lib/utils/css-classes'
import { WIZARD_HOG_URL } from 'scenes/onboarding/shared/wizardHog'

import androidImage from '../../legacy/sdks/logos/android.svg'
import angularImage from '../../legacy/sdks/logos/angular.svg'
import { AstroLogo } from '../../legacy/sdks/logos/AstroLogo'
import djangoImage from '../../legacy/sdks/logos/django.svg'
import flaskImage from '../../legacy/sdks/logos/flask.svg'
import { IOSLogo } from '../../legacy/sdks/logos/IOSLogo'
import laravelImage from '../../legacy/sdks/logos/laravel.svg'
import nextjsImage from '../../legacy/sdks/logos/nextjs.svg'
import nuxtImage from '../../legacy/sdks/logos/nuxt.svg'
import pythonImage from '../../legacy/sdks/logos/python.svg'
import railsImage from '../../legacy/sdks/logos/rails.svg'
import reactImage from '../../legacy/sdks/logos/react.svg'
import { ReactRouterLogo } from '../../legacy/sdks/logos/ReactRouterLogo'
import svelteImage from '../../legacy/sdks/logos/svelte.svg'
import vueImage from '../../legacy/sdks/logos/vue.svg'

// Frameworks the wizard can set up — the same whichever way it runs, so both modes show them.
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

export function WizardFrameworkBadges(): JSX.Element {
    return (
        <div className="flex flex-wrap gap-1.5 items-center justify-center">
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
    )
}

/**
 * Shared chrome for both install modes, so the cloud and local tabs read as one
 * wizard rather than two unrelated panels: the hedgehog on the left, the
 * mode-specific content on the right. The framework badges are rendered once
 * above the mode selector (shared by both), not here. `hogCastKey` replays the
 * hog's "casting" wobble when bumped — the command tab bumps it on copy; the
 * cloud tab leaves it at 0 (a static hog).
 */
export function WizardModeShell({
    children,
    hogCastKey = 0,
    hideHog = false,
    'data-attr': dataAttr,
}: {
    children: ReactNode
    hogCastKey?: number
    /** Drop the hedgehog (e.g. the compact context-first onboarding card has no room for it). */
    hideHog?: boolean
    'data-attr'?: string
}): JSX.Element {
    return (
        <div className="flex gap-6" data-attr={dataAttr}>
            {!hideHog && (
                <img
                    key={`hog-${hogCastKey}`}
                    src={WIZARD_HOG_URL}
                    alt="PostHog wizard hedgehog"
                    className={cn(
                        'w-28 h-28 hidden sm:block shrink-0 self-center',
                        hogCastKey > 0 && 'WizardModeShell__hogCast'
                    )}
                />
            )}
            {/* With the hog hidden (compact context-first card), center the content at its natural
                width instead of stretching it full-bleed — so the command block and the GitHub-connect
                block sit centered without expanding. With the hog shown, keep the left-aligned column. */}
            <div className={cn('flex-1 flex flex-col justify-center gap-3', hideHog && 'items-center text-center')}>
                {children}
            </div>
        </div>
    )
}
