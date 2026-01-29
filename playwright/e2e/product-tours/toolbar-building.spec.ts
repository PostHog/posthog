import { Page } from '@playwright/test'

import { locateByDataAttr, randomString } from '../../utils'
import { expect, test } from '../../utils/playwright-test-base'

const getDemoUrl = async (page: Page): Promise<string> => {
    const loc = await page.evaluate(() => window.location)
    return `${loc.protocol}//${loc.host}/demo`
}

test.describe('Product Tours - Toolbar Building', () => {
    test.beforeEach(async ({ page }) => {
        // Inject flag into POSTHOG_APP_CONTEXT before page scripts run
        await page.addInitScript(() => {
            let _context: any = null
            Object.defineProperty(window, 'POSTHOG_APP_CONTEXT', {
                get() {
                    return _context
                },
                set(value) {
                    _context = {
                        ...value,
                        persisted_feature_flags: [...(value?.persisted_feature_flags || []), 'product-tours-2025'],
                    }
                },
                configurable: true,
            })
        })

        await page.reload()
        await page.waitForLoadState('domcontentloaded')

        // Wait for menu item to appear
        await page.getByTestId('menu-item-product-tours').waitFor({ state: 'visible', timeout: 15000 })

        await page.goToMenuItem('product-tours')
        await expect(page.locator('h1')).toContainText('Product tours')

        const createButton = await locateByDataAttr(page, 'new-product-tour')
        await expect(createButton).toBeVisible()
        await createButton.click()

        await expect(page.getByText('What would you like to create?')).toBeVisible()

        const tourCreateButton = await locateByDataAttr(page, 'tour-type-selection-button__tour')
        await expect(tourCreateButton).toBeVisible()

        await tourCreateButton.click()

        await expect(page.getByText('Select a URL to launch the toolbar and create your product tour')).toBeVisible()

        const demoUrl = await getDemoUrl(page)
        const hasDemoUrl = await page
            .getByText(demoUrl)
            .isVisible()
            .catch(() => false)

        if (!hasDemoUrl) {
            ;(await locateByDataAttr(page, 'toolbar-add-url')).click()
            const urlInput = await locateByDataAttr(page, 'url-input')

            await urlInput.fill(demoUrl)

            const saveResponsePromise = page.waitForResponse(
                (resp) => resp.url().includes('/api/environments') && resp.request().method() === 'PATCH'
            )

            ;(await locateByDataAttr(page, 'url-save')).click()
            await saveResponsePromise
        }
    })

    test('Can launch toolbar and create product tour', async ({ page, context }) => {
        const demoUrl = await getDemoUrl(page)

        const urlRow = page.locator(`span[title="${demoUrl}"]`).locator('..')
        const toolbarLink = urlRow.locator('[data-attr="toolbar-open"]')
        await expect(toolbarLink).toBeVisible()

        const [toolbarPage] = await Promise.all([context.waitForEvent('page'), toolbarLink.click()])

        await toolbarPage.waitForLoadState()

        const toolbar = toolbarPage.locator('#__POSTHOG_TOOLBAR__')
        await expect(toolbar).toBeInViewport()

        const sidebar = toolbar.locator('[data-attr="product-tours-toolbar-sidebar"]')
        await expect(sidebar).toBeVisible()

        await expect(sidebar.getByText('No steps yet')).toBeVisible()

        const newStepButton = sidebar.locator('[data-attr="new-step-button"]')
        await newStepButton.click()

        await toolbar.locator('[data-attr="new-tour-step__element"]').click()
        ;(await locateByDataAttr(toolbarPage, 'sign-up-button')).click()

        await newStepButton.click()
        await toolbar.locator('[data-attr="new-tour-step__modal"]').click()

        const stepList = await sidebar.locator('[data-attr="product-tour-step-list"] > div').all()
        expect(stepList).toHaveLength(2)

        const elementStep = stepList[0]
        await elementStep.click()

        await expect(elementStep.getByText('Element', { exact: true })).toBeVisible()

        const screenshot = elementStep.getByAltText('Element preview')
        await expect(screenshot).toBeVisible()
        await expect(screenshot).toHaveAttribute('src', /\/uploaded_media\//)

        await expect(elementStep.locator('li').filter({ hasText: 'Auto' })).toHaveClass(/--selected/)
        await expect(elementStep.locator('li').filter({ hasText: 'Manual' })).not.toHaveClass(/--selected/)

        await expect(elementStep.locator('li').filter({ hasText: 'Next button' })).toHaveClass(/--selected/)
        await expect(elementStep.locator('li').filter({ hasText: 'Element click' })).not.toHaveClass(/--selected/)

        const tourName = `Test Tour ${randomString()}`
        await sidebar.locator('[data-attr="product-tour-title-input"]').fill(tourName)

        const saveResponsePromise = toolbarPage.waitForResponse(
            (resp) =>
                resp.url().includes('/api/projects/') &&
                resp.url().includes('/product_tours') &&
                resp.request().method() === 'POST'
        )
        await sidebar.locator('button').getByText('Save').first().click()
        await saveResponsePromise

        await expect(toolbar.locator('[data-attr="success-toast"]').getByText('Tour created')).toBeVisible()

        await page.bringToFront()
        await toolbarPage.close()

        await page.goto('/product_tours')
        await page.waitForLoadState('domcontentloaded')

        const table = page.locator('[data-attr="product-tours-table"]')
        await expect(table).toBeVisible()

        const row = table.locator('tr').filter({ hasText: tourName })
        await expect(row).toBeVisible()

        const moreButton = row.locator('[data-attr="more-button"]')
        await moreButton.click()

        await page.locator('button').getByText('Delete', { exact: true }).click()

        const deleteResponsePromise = page.waitForResponse(
            (resp) =>
                resp.url().includes('/api/projects/') &&
                resp.url().includes('/product_tours') &&
                resp.request().method() === 'DELETE'
        )
        await (await locateByDataAttr(page, 'product-tour-table-action-button__confirm-delete')).click()
        await deleteResponsePromise

        await expect(table.locator('tr').filter({ hasText: tourName })).not.toBeVisible()
    })
})
