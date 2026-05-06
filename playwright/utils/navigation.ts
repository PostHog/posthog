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
        // Use navbar-specific selector for items that have duplicates in LemonTree
        const navbarSelector = this.page.getByTestId(`navbar-${name}`)
        const menuSelector = this.page.getByTestId(`menu-item-${name}`)
        const navItemSelector = this.page.getByTestId(`nav-item-${name === 'projecthomepage' ? 'home' : name}`)

        // Prefer navbar selector, then menu-item, then ai-first nav-item
        let element = navbarSelector
        if ((await navbarSelector.count()) === 0) {
            element = (await menuSelector.count()) > 0 ? menuSelector : navItemSelector
        }

        if ((await element.count()) === 0 && IDENTIFIER_URL_FALLBACKS[name]) {
            // No nav element exists in the AI-first navigation for this scene; navigate by URL
            await this.page.goto(IDENTIFIER_URL_FALLBACKS[name])
        } else {
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
