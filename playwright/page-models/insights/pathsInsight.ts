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
        // Wait for the paths container to appear in the DOM first (handles slow page loads)
        await this.container.waitFor({ state: 'attached', timeout: 30000 })
        const loading = this.page.getByTestId('insight-loading-waiting-message')
        await loading.waitFor({ state: 'attached', timeout: 2000 }).catch(() => {})
        await loading.waitFor({ state: 'detached', timeout: 30000 })
        await expect(this.container).toBeVisible({ timeout: 15000 })
    }

    async waitForNodes(): Promise<void> {
        await this.waitForChart()
        await expect(this.pathNodes.first()).toBeVisible({ timeout: 30000 })
    }

    async selectEventType(type: 'Page views' | 'Screen views' | 'Custom event'): Promise<void> {
        await this.eventTypeButton.click()
        // Check the desired type first (so it's not the only one),
        // then uncheck "Page views" if switching away from it.
        const targetItem = this.page.getByTestId(EVENT_TYPE_ATTRS[type])
        await targetItem.click()
        if (type !== 'Page views') {
            await this.page.getByTestId(EVENT_TYPE_ATTRS['Page views']).click()
        }
        await this.page.keyboard.press('Escape')
    }

    async selectSteps(steps: number): Promise<void> {
        await this.stepsButton.click()
        await this.page.getByRole('menuitem', { name: `${steps} Steps` }).click()
    }

    /** Extract structured node data: name (path/event) and person count. */
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
