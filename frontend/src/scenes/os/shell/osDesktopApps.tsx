import { IconGear, IconStore } from '@posthog/icons'

import { urls } from 'scenes/urls'

import type { FlatNavProductGroup } from '~/layout/panel-layout/navbar/tabs/flat-nav/flatNavLogic'
import { iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'

import type { GlyphPart } from './glass/GlassIcon'
import { CHANGELOG_GLYPH, DOCS_GLYPH, HOME_GLYPH } from './glass/glyphs'

export type OsDesktopAppIcon =
    | { kind: 'glyph'; path: string | GlyphPart[]; viewBox?: string; fillRule?: 'nonzero' | 'evenodd' }
    /** An app icon, drawn as glass when it paints only paths. */
    | { kind: 'element'; element: JSX.Element }

export interface OsDesktopApp {
    key: string
    label: string
    href: string
    /** Opens in a new browser tab, because the site refuses to load inside a window. */
    external?: boolean
    /** Drawn in the accent color. Only the App Store has it, so it reads as the place to get more apps. */
    highlighted?: boolean
    icon: OsDesktopAppIcon
}

export interface OsDesktopColumns {
    left: OsDesktopApp[]
    right: OsDesktopApp[]
}

/**
 * The desktop mirrors posthog.com: the user's picked tools run down the left edge after home,
 * and the system apps sit on the right edge.
 */
export function osDesktopColumns(productGroups: FlatNavProductGroup[]): OsDesktopColumns {
    const home: OsDesktopApp = {
        key: 'home',
        label: 'Home',
        href: urls.projectHomepage(),
        icon: { kind: 'glyph', path: HOME_GLYPH },
    }
    const tools = productGroups.flatMap(({ items }) =>
        items.map(
            (item): OsDesktopApp => ({
                key: `tool-${item.path}`,
                label: item.label,
                href: item.href,
                icon: { kind: 'element', element: iconForType(item.iconType, item.iconColor) },
            })
        )
    )

    return {
        left: [home, ...tools],
        right: [
            {
                key: 'app-store',
                label: 'App Store',
                href: urls.osAppStore(),
                highlighted: true,
                icon: { kind: 'element', element: <IconStore /> },
            },
            {
                key: 'settings',
                label: 'Settings',
                href: urls.settings(),
                icon: { kind: 'element', element: <IconGear /> },
            },
            {
                key: 'docs',
                label: 'Docs',
                href: 'https://posthog.com/docs',
                external: true,
                icon: { kind: 'glyph', path: DOCS_GLYPH, fillRule: 'evenodd' },
            },
            {
                key: 'changelog',
                label: 'Changelog',
                href: 'https://posthog.com/changelog',
                external: true,
                icon: { kind: 'glyph', path: CHANGELOG_GLYPH },
            },
        ],
    }
}
