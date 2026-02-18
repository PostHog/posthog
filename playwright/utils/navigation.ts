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

        // Prefer navbar selector if it exists, fall back to menu-item
        const element = (await navbarSelector.count()) > 0 ? navbarSelector : menuSelector
        await element.click()
        // Wait for navigation to complete and page to be ready
        await this.page.waitForLoadState('domcontentloaded')
        // Additional wait with timeout for network to settle (catches lazy-loaded components)
        await this.page.waitForLoadState('networkidle', { timeout: 5000 }).catch(() => {
            // Ignore timeout - networkidle may not occur with long-polling
        })
    }
}
