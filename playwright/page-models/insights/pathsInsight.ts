import { Locator, Page, expect } from '@playwright/test'

export interface PathNode {
    name: string
    count: number
}

const EVENT_TYPE_ATTRS: Record<string, string> = {
    'Page views': 'path-type-$pageview',
    'Screen views': 'path-type-$screen',
    'Custom event': 'path-type-custom_event',
}

export class PathsInsight {
    readonly container: Locator
    readonly eventTypeButton: Locator
    readonly stepsButton: Locator
    readonly startPointButton: Locator
    readonly endPointButton: Locator
    readonly pathNodes: Locator

    constructor(private readonly page: Page) {
        this.container = page.getByTestId('paths-viz')
        this.eventTypeButton = page.getByRole('button', { name: /Page views|Screen views|Custom event/ })
        this.stepsButton = page.getByRole('button', { name: /\d+ Steps/ })
        this.startPointButton = page.getByRole('button', { name: 'Add start point' })
        this.endPointButton = page.getByRole('button', { name: 'Add end point' })
        this.pathNodes = this.container.getByTestId('path-node-card-button')
    }

    async waitForChart(): Promise<void> {
        await this.container.waitFor({ state: 'attached', timeout: 15000 })
        const loading = this.page.getByTestId('insight-loading-waiting-message')
        await loading.waitFor({ state: 'detached', timeout: 15000 })
        await expect(this.container).toBeVisible()
    }

    async waitForNodes(): Promise<void> {
        await this.waitForChart()
        await expect(this.pathNodes.first()).toBeVisible({ timeout: 15000 })
    }

    async selectEventType(type: 'Page views' | 'Screen views' | 'Custom event'): Promise<void> {
        await this.eventTypeButton.click()
        for (const [name, testId] of Object.entries(EVENT_TYPE_ATTRS)) {
            const item = this.page.getByTestId(testId)
            const isChecked = await item.getByRole('checkbox').isChecked()
            const shouldBeChecked = name === type
            if (isChecked !== shouldBeChecked) {
                await item.click()
            }
        }
        await this.page.keyboard.press('Escape')
    }

    async selectSteps(steps: number): Promise<void> {
        await this.stepsButton.click()
        await this.page.getByRole('menuitem', { name: `${steps} Steps` }).click()
    }

    async getNodes(): Promise<PathNode[]> {
        const count = await this.pathNodes.count()
        const nodes: PathNode[] = []
        for (let i = 0; i < count; i++) {
            const node = this.pathNodes.nth(i)
            const name = await node.getByTestId('path-node-name').textContent()
            const countText = await node.getByTestId('path-node-count').textContent()
            if (name && countText) {
                nodes.push({ name: name.trim(), count: Number(countText.trim()) })
            }
        }
        return nodes
    }
}
