import './WizardModeShell.scss'

import type { ComponentType, ReactNode } from 'react'

import { cn } from 'lib/utils/css-classes'
import { WizardHog } from 'scenes/onboarding/shared/wizardHog'

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

/** The hedgehog beside the wizard's content; `null` drops it, e.g. when an outer shell already shows one. */
export type WizardShellHog = ComponentType<{ className?: string }> | null

/** One "Supports:" chip; icon-less items (e.g. "+ 30 more") render as text only. */
export interface WizardBadgeItem {
    name: string
    icon?: string | ComponentType
}

// Frameworks the wizard can set up — the same whichever way it runs, so both modes show them.
export const WIZARD_FRAMEWORKS: WizardBadgeItem[] = [
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

const ICON_SIZE_CLASSES = {
    sm: 'w-3 h-3 [&_svg]:!w-3 [&_svg]:!h-3',
    md: 'w-4 h-4 [&_svg]:!w-4 [&_svg]:!h-4',
}

export function WizardFrameworkIcon({
    icon: Icon,
    size,
}: {
    icon: NonNullable<WizardBadgeItem['icon']>
    size: keyof typeof ICON_SIZE_CLASSES
}): JSX.Element {
    return (
        <span className={cn('inline-flex shrink-0', ICON_SIZE_CLASSES[size])}>
            {typeof Icon === 'string' ? <img src={Icon} alt="" className="w-full h-full" /> : <Icon />}
        </span>
    )
}

export function WizardFrameworkBadges({ items = WIZARD_FRAMEWORKS }: { items?: WizardBadgeItem[] } = {}): JSX.Element {
    return (
        <div className="flex flex-wrap gap-1.5 items-center justify-center">
            <span className="text-xs text-muted">Supports:</span>
            {items.map((fw) => (
                <span
                    key={fw.name}
                    className="inline-flex items-center gap-1 text-xs text-muted bg-bg-light border border-border rounded px-1.5 py-0.5"
                >
                    {fw.icon ? <WizardFrameworkIcon icon={fw.icon} size="sm" /> : null}
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
    hog: Hog = WizardHog,
    'data-attr': dataAttr,
}: {
    children: ReactNode
    hogCastKey?: number
    hog?: WizardShellHog
    'data-attr'?: string
}): JSX.Element {
    return (
        <div className="flex gap-6" data-attr={dataAttr}>
            {Hog && (
                <Hog
                    key={`hog-${hogCastKey}`}
                    className={cn(
                        'w-28 h-28 hidden sm:block shrink-0 self-center',
                        hogCastKey > 0 && 'WizardModeShell__hogCast'
                    )}
                />
            )}
            <div className="flex-1 flex flex-col justify-center gap-3 min-w-0">{children}</div>
        </div>
    )
}
