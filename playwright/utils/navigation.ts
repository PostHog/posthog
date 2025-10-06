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
        await this.page.goto(urls.projectHomepage())
    }

    async openMenuItem(name: string): Promise<void> {
        await this.page.getByTestId(`menu-item-${name}`).click()
    }
}
