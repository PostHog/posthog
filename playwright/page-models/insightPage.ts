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

    readonly personsModal: Locator
    readonly personsModalViewEventsButton: Locator

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
        this.activeTab = page.locator('.LemonTabs__tab--active')

        this.personsModal = page.getByTestId('persons-modal')
        this.personsModalViewEventsButton = page.getByTestId('person-modal-view-events')

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
        await this.activeTab.waitFor({ state: 'visible' })
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

        let url = base
        if (options?.queryParams) {
            const params = new URLSearchParams()
            for (const [k, v] of Object.entries(options.queryParams)) {
                params.set(k, typeof v === 'object' ? JSON.stringify(v) : String(v))
            }
            const sep = base.includes('?') ? '&' : '?'
            url = `${base}${sep}${params}`
        }

        const insightLoaded = this.waitForInsightLoad()
        await this.page.goto(url, { waitUntil: 'domcontentloaded' })
        await insightLoaded
        return this
    }

    async save(): Promise<void> {
        const originalUrl = this.page.url()
        const originalPathname = new URL(originalUrl).pathname

        // Wait for any in-progress query to finish — the save button uses aria-disabled while queries run
        await expect(this.saveButton).not.toHaveAttribute('aria-disabled', 'true', { timeout: 60000 })

        const saveRequestPromise = this.page.waitForResponse(
            (response) =>
                /\/api\/(?:projects|environments)\/\d+\/insights(?:\/\d+)?\/?(?:\?.*)?$/.test(response.url()) &&
                ['POST', 'PATCH'].includes(response.request().method()),
            { timeout: 30000 }
        )

        // Saving switches back to view mode, which re-fetches the insight. Drain that
        // fetch before returning — left in flight, its response can land after a later
        // edit and clobber it (see waitForInsightLoad).
        const insightReloaded = this.waitForInsightLoad()

        await this.saveButton.click()

        const saveResponse = await saveRequestPromise

        if (saveResponse.status() >= 400) {
            const errorToast = this.page.locator('[data-attr="error-toast"]').first()
            const errorText = (await errorToast.textContent().catch(() => null))?.trim()
            throw new Error(`Insight save failed with ${saveResponse.status()}${errorText ? `: ${errorText}` : ''}`)
        }

        const successToast = this.page
            .locator('[data-attr="success-toast"]')
            .filter({ hasText: 'Insight saved' })
            .first()
        const errorToast = this.page.locator('[data-attr="error-toast"]').first()

        await expect(async () => {
            const currentPathname = new URL(this.page.url()).pathname

            if (await errorToast.isVisible().catch(() => false)) {
                const errorText = (await errorToast.textContent().catch(() => null))?.trim()
                throw new Error(`Insight save showed an error toast${errorText ? `: ${errorText}` : ''}`)
            }

            if (currentPathname !== originalPathname) {
                return
            }

            if (await this.editButton.isVisible().catch(() => false)) {
                return
            }

            await expect(successToast.or(this.editButton)).toBeVisible()
        }).toPass({ timeout: 30000 })

        if (new URL(this.page.url()).pathname === originalPathname) {
            await expect(this.editButton).toBeVisible()
        }

        await insightReloaded
    }

    // Both navigating to an insight and entering edit mode trigger a re-fetch of the
    // insight (GET ?short_id=...). If a test edits the query while that fetch is in
    // flight, the response clobbers the local edit and the page reverts to a clean
    // "No changes" state. Wait for the fetch so edits made afterwards stick.
    private waitForInsightLoad(): Promise<unknown> {
        return this.page.waitForResponse(
            (response) =>
                /\/api\/(?:projects|environments)\/\d+\/insights\/?\?(?=.*\bshort_id=)/.test(response.url()) &&
                response.request().method() === 'GET',
            { timeout: 30000 }
        )
    }

    async edit(): Promise<void> {
        const insightLoaded = this.waitForInsightLoad()
        await this.editButton.click()
        await insightLoaded
    }

    async discard(): Promise<void> {
        // Discarding switches back to view mode, which re-fetches the insight. Drain that
        // fetch before returning — left in flight, its response can land after a later
        // edit and clobber it (see waitForInsightLoad).
        const insightReloaded = this.waitForInsightLoad()
        await this.page.getByTestId('insight-cancel-edit-button').click()
        await expect(this.editButton).toBeVisible()
        await insightReloaded
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
        // Click the static `role="img"` canvas — the quill chart also renders an
        // `aria-hidden` overlay canvas, so an unscoped `canvas` would match two.
        await this.page.locator('.TrendsInsight canvas[role="img"]').click()
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
