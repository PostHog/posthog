import { Locator, Page, expect } from '@playwright/test'

import { urls } from 'scenes/urls'

import { InsightShortId, InsightType } from '~/types'

import { randomString } from '../utils'
import { FunnelsInsight } from './insights/funnelsInsight'
import { LifecycleInsight } from './insights/lifecycleInsight'
import { PathsInsight } from './insights/pathsInsight'
import { RetentionInsight } from './insights/retentionInsight'
import { SqlInsight } from './insights/sqlInsight'
import { StickinessInsight } from './insights/stickinessInsight'
import { TrendsInsight } from './insights/trendsInsight'

export class InsightPage {
    readonly page: Page

    // top bar
    readonly saveButton: Locator
    readonly editButton: Locator
    readonly cancelButton: Locator
    readonly topBarName: Locator
    readonly activeTab: Locator

    readonly trends: TrendsInsight
    readonly funnels: FunnelsInsight
    readonly retention: RetentionInsight
    readonly paths: PathsInsight
    readonly stickiness: StickinessInsight
    readonly lifecycle: LifecycleInsight
    readonly sql: SqlInsight

    constructor(page: Page) {
        this.page = page

        this.saveButton = page.getByTestId('insight-save-button')
        this.editButton = page.getByTestId('insight-edit-button')
        this.cancelButton = page.getByTestId('insight-cancel-edit-button')
        this.topBarName = page.getByTestId('scene-name')
        this.activeTab = page.getByRole('tab', { selected: true })

        this.trends = new TrendsInsight(page)
        this.funnels = new FunnelsInsight(page)
        this.retention = new RetentionInsight(page)
        this.paths = new PathsInsight(page)
        this.stickiness = new StickinessInsight(page)
        this.lifecycle = new LifecycleInsight(page)
        this.sql = new SqlInsight(page)
    }

    async goToList(): Promise<InsightPage> {
        await this.page.goto(urls.savedInsights(), { waitUntil: 'domcontentloaded' })
        return this
    }

    async goToNewInsight(type: InsightType): Promise<InsightPage> {
        await this.page.goto(urls.insightNew({ type }), { waitUntil: 'domcontentloaded' })
        await this.page.getByRole('tab', { selected: true }).waitFor({ state: 'visible' })
        return this
    }

    async goToNewTrends(): Promise<InsightPage> {
        return this.goToNewInsight(InsightType.TRENDS)
    }

    async goToSql(): Promise<InsightPage> {
        await this.page.goto('/sql', { waitUntil: 'domcontentloaded' })
        return this
    }

    async goToInsight(
        shortId: InsightShortId,
        options?: { edit?: boolean; queryParams?: Record<string, string | number | object> }
    ): Promise<InsightPage> {
        const base = options?.edit ? urls.insightEdit(shortId) : urls.insightView(shortId)

        if (!options?.queryParams) {
            await this.page.goto(base, { waitUntil: 'domcontentloaded' })
            return this
        }

        const params = new URLSearchParams()
        for (const [k, v] of Object.entries(options.queryParams)) {
            params.set(k, typeof v === 'object' ? JSON.stringify(v) : String(v))
        }
        const sep = base.includes('?') ? '&' : '?'
        await this.page.goto(`${base}${sep}${params}`, { waitUntil: 'domcontentloaded' })
        return this
    }

    async save(): Promise<void> {
        await this.saveButton.click()
        await this.page.waitForURL(/^(?!.*\/new$).+$/)
        await expect(this.editButton).toBeVisible()
    }

    async edit(): Promise<void> {
        await this.editButton.click()
    }

    async discard(): Promise<void> {
        await this.page.getByTestId('insight-cancel-edit-button').click()
        await expect(this.editButton).toBeVisible()
    }

    async editName(insightName: string = randomString('insight')): Promise<void> {
        const nameField = this.page.getByTestId('scene-title-textarea')
        await expect(nameField).toBeVisible()
        await nameField.click()
        await nameField.fill(insightName)
        await nameField.blur()
    }

    async createNew(name: string, type: InsightType): Promise<InsightPage> {
        await this.goToNewInsight(type)
        await this.editName(name)
        return this
    }

    async goToNew(type: InsightType): Promise<InsightPage> {
        return this.goToNewInsight(type)
    }

    async openPersonsModal(): Promise<void> {
        await this.page.locator('.TrendsInsight canvas').click()
        await this.page.waitForSelector('[data-attr="persons-modal"]', { state: 'visible' })
    }

    async openInfoPanel(): Promise<void> {
        const sidePanelButton = this.page.locator('#main-content').getByTestId('open-context-panel-button')
        await sidePanelButton.click()
        // The side panel is lazy-loaded via React.lazy + Suspense. Wait for the
        // panel container to be visible so callers know the panel has mounted and
        // the portal target is registered.
        await this.page.locator('#side-panel').waitFor({ state: 'visible' })
        // The insight panel content is rendered via createPortal into a target
        // registered by SidePanelInfo's useEffect. Waiting for #side-panel alone
        // doesn't guarantee the portal target has switched from the hidden inline
        // panel (Navigation.tsx). Wait for portal content to appear *inside*
        // #side-panel, confirming the switch is complete. Scoping to #side-panel
        // avoids matching the hidden inline panel.
        await this.page.locator('#side-panel .scene-panel-actions-section').first().waitFor({ state: 'visible' })
    }

    async clickDeleteInsight(): Promise<void> {
        // The delete button is rendered via createPortal into scenePanelElement.
        // There are two portal targets: a hidden inline panel (Navigation.tsx,
        // display: none for insights) and the visible side panel (SidePanelInfo).
        // After opening the Info tab the portal content moves from the inline
        // panel to the side panel via useEffect. Scope the locator to #side-panel
        // so we wait for the button in the visible container, not the hidden one.
        const deleteButton = this.page.locator('#side-panel').getByTestId('insight-delete')
        await deleteButton.waitFor({ state: 'visible' })
        await deleteButton.click()
    }

    async confirmDeleteDialog(): Promise<void> {
        const dialog = this.page.locator('.LemonModal').filter({ hasText: 'Delete insight?' })
        await expect(dialog).toBeVisible()
        await dialog.getByRole('button', { name: 'Delete' }).click()
    }

    async cancelDeleteDialog(): Promise<void> {
        const dialog = this.page.locator('.LemonModal').filter({ hasText: 'Delete insight?' })
        await expect(dialog).toBeVisible()
        await dialog.getByRole('button', { name: 'Cancel' }).click()
        await expect(dialog).not.toBeVisible()
    }

    async saveAsNew(name: string): Promise<void> {
        const originalUrl = this.page.url()
        await this.page.locator('[data-attr="insight-save-dropdown"]').click()
        await this.page.locator('[data-attr="insight-save-as-new-insight"]').click()
        const nameInput = this.page.getByPlaceholder('Please enter the new name')
        await nameInput.waitFor({ state: 'visible' })
        await nameInput.fill(name)
        await this.page.getByRole('button', { name: 'Submit' }).click()
        await this.page.waitForURL((url) => url.toString() !== originalUrl, { timeout: 15000 })
    }
}
