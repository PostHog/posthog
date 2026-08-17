import { DashboardPage } from '@playwright-pages/dashboardPage'
import { expect, test } from '@playwright-utils/workspace-test-base'

test.describe('Dashboard sections', () => {
    test('adds a tile to new rows at the bottom of a section', async ({ page, playwrightSetup }) => {
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

        const sectionHeader = page.getByTestId('dashboard-section-header').filter({ hasText: 'New section' })
        await expect(sectionHeader).toContainText('0 tiles')
        await page.waitForTimeout(300)

        const secondTile = dashboard.textCards.filter({ hasText: 'Second tile' })
        const firstTile = dashboard.textCards.filter({ hasText: 'First tile' })
        await firstTile.getByRole('button', { name: 'more' }).click()
        await page.getByTestId('dashboard-tile-move-to-section').click()
        await page.getByRole('menuitem', { name: 'New section' }).click()

        await expect(sectionHeader).toContainText('1 tile')
        await dashboard.enterEditMode()
        await expect.poll(async () => (await sectionHeader.locator('..').boundingBox())!.height).toBeGreaterThan(200)
        await page.waitForTimeout(300)

        const secondTileBody = secondTile.locator('.TextCard__body')
        const secondTileBox = await secondTileBody.boundingBox()
        const populatedSectionBox = await sectionHeader.locator('..').boundingBox()
        expect(secondTileBox).not.toBeNull()
        expect(populatedSectionBox).not.toBeNull()

        const secondTileDragX = secondTileBox!.x + 20
        const secondTileDragY = secondTileBox!.y + secondTileBox!.height - 30
        await secondTileBody.hover({ position: { x: 20, y: secondTileBox!.height - 30 } })
        await page.mouse.down()
        await page.mouse.move(secondTileDragX + 30, secondTileDragY - 30, { steps: 5 })
        await expect(secondTile).toHaveClass(/react-draggable-dragging/)
        await page.mouse.move(populatedSectionBox!.x + populatedSectionBox!.width / 2, populatedSectionBox!.y + 20, {
            steps: 20,
        })
        const tileDropSpace = page.getByTestId('dashboard-section-tile-drop-space')
        await expect(tileDropSpace).toBeVisible()
        const tileDropSpaceBox = await tileDropSpace.boundingBox()
        expect(tileDropSpaceBox).not.toBeNull()
        await page.mouse.move(
            tileDropSpaceBox!.x + tileDropSpaceBox!.width / 2,
            tileDropSpaceBox!.y + tileDropSpaceBox!.height - 100,
            { steps: 10 }
        )
        await expect(tileDropSpace).toBeVisible()
        await page.mouse.up()
        await expect(sectionHeader).toContainText('2 tiles')
        await expect(tileDropSpace).not.toBeVisible()
    })
})
