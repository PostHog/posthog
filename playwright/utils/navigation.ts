import { Page } from '@playwright/test'

import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

type LowercaseEnum<T> = {
    [K in keyof T]: T[K] extends string ? Lowercase<T[K]> : never
}[keyof T]

/** Derive possible identifiers from the Scene enum. Not all of them are
 * actually nav items. This will help keep e2e tests up-to-date when
 * refactoring scenes though. */
export type Identifier = LowercaseEnum<typeof Scene>

const IDENTIFIER_URL_FALLBACKS: Record<string, string> = {
    projecthomepage: urls.projectHomepage(),
    activity: urls.activity(),
    datamanagement: urls.eventDefinitions(),
    'event-definitions': urls.eventDefinitions(),
    annotations: urls.annotations(),
    toolbar: urls.toolbarLaunch(),
    'sql-editor': urls.sqlEditor(),
    settings: urls.settings(),
    surveys: '/surveys',
    cohorts: '/cohorts',
    dashboards: '/dashboard',
    people: '/persons',
    persons: '/persons',
    action: '/data-management/actions',
    'product-analytics': '/insights',
    insight: '/insights/new',
    insights: '/insights',
}

export class Navigation {
    readonly page: Page

    constructor(page: Page) {
        this.page = page
    }

    async openHome(): Promise<void> {
        await this.page.goto(urls.projectRoot())
    }

    async openMenuItem(name: string): Promise<void> {
        // The legacy PanelLayoutNavBar exposed every scene as `menu-item-<name>` /
        // `navbar-<name>`. The AI-first navbar only renders a few `nav-item-*` test-ids
        // (and only when the parent collapsible section is expanded), so for known scenes
        // we navigate by URL — that's the most reliable cross-layout behavior.
        if (IDENTIFIER_URL_FALLBACKS[name]) {
            await this.page.goto(IDENTIFIER_URL_FALLBACKS[name])
        } else {
            // Fall back to legacy selectors for scenes we haven't mapped yet.
            const navbarSelector = this.page.getByTestId(`navbar-${name}`)
            const menuSelector = this.page.getByTestId(`menu-item-${name}`)
            const element = (await navbarSelector.count()) > 0 ? navbarSelector : menuSelector
            await element.click()
        }
        // Wait for navigation to complete and page to be ready
        await this.page.waitForLoadState('domcontentloaded')
        // Additional wait with timeout for network to settle (catches lazy-loaded components)
        await this.page.waitForLoadState('networkidle', { timeout: 5000 }).catch(() => {
            // Ignore timeout - networkidle may not occur with long-polling
        })
    }
}
