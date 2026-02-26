import { Locator, Page, expect } from '@playwright/test'

import { urls } from 'scenes/urls'

import { InsightType } from '~/types'

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
        this.topBarName = page.locator('.scene-name')
        this.activeTab = page.locator('.LemonTabs__tab--active')

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
        await this.page.waitForSelector('.LemonTabs__tab--active')
        return this
    }

    async goToNewTrends(): Promise<InsightPage> {
        return this.goToNewInsight(InsightType.TRENDS)
    }

    async goToSql(): Promise<InsightPage> {
        await this.page.goto('/sql', { waitUntil: 'domcontentloaded' })
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
