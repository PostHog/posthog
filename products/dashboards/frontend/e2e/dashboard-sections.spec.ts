import { DashboardPage } from '@playwright-pages/dashboardPage'
import { expect, test } from '@playwright-utils/workspace-test-base'

test.describe('Dashboard sections', () => {
    test('moves a tile into and out of a section', async ({ page, playwrightSetup }) => {
        const workspace = await playwrightSetup.createWorkspace({ skip_onboarding: true })
        await playwrightSetup.login(page, workspace)

        const dashboard = new DashboardPage(page)
        await dashboard.createNew()
        await dashboard.addTextCard('First tile')
        await dashboard.enterEditMode()
        await page.getByTestId('dashboard-add-tile').click()
        await page.getByTestId('dashboard-add-section').click()

        await dashboard.addTextCard('Second tile')
        await dashboard.addTextCard('Third tile')
        await dashboard.addTextCard('Fourth tile')
        await dashboard.addTextCard('Fifth tile')
        await dashboard.addTextCard('Sixth tile')
        await dashboard.addTextCard('Seventh tile')
        await dashboard.addTextCard('Eighth tile')

        const sectionHeader = page.getByTestId('dashboard-section-header').filter({ hasText: 'New section' })
        await expect(sectionHeader).toContainText('0 tiles')

        const dragHandle = dashboard.textCards.filter({ hasText: 'First tile' }).locator('.TextCard__body')
        const looseTile = dashboard.textCards.filter({ hasText: 'Second tile' })
        const sourceBox = await dragHandle.boundingBox()
        const targetBox = await sectionHeader.boundingBox()
        expect(sourceBox).not.toBeNull()
        expect(targetBox).not.toBeNull()

        await page.mouse.move(sourceBox!.x + sourceBox!.width / 2, sourceBox!.y + sourceBox!.height / 2)
        await page.mouse.down()
        await page.mouse.move(targetBox!.x + targetBox!.width / 2, targetBox!.y + targetBox!.height / 2, { steps: 20 })
        await expect(sectionHeader.locator('..')).toHaveClass(/border-accent/)
        await page.mouse.up()

        await expect(sectionHeader).toContainText('1 tile')
        await expect.poll(async () => (await sectionHeader.locator('..').boundingBox())!.height).toBeGreaterThan(200)
        await page.waitForTimeout(300)

        const movedTile = dashboard.textCards.filter({ hasText: 'First tile' }).locator('.TextCard__body')
        const movedTileBox = await movedTile.boundingBox()
        const looseTileBox = await looseTile.locator('.TextCard__body').boundingBox()
        await page.mouse.move(movedTileBox!.x + movedTileBox!.width / 2, movedTileBox!.y + movedTileBox!.height / 2)
        await page.mouse.down()
        await page.mouse.move(looseTileBox!.x + looseTileBox!.width / 2, looseTileBox!.y + looseTileBox!.height / 2, {
            steps: 20,
        })
        await page.mouse.up()
        await expect(sectionHeader).toContainText('0 tiles')
    })
})
