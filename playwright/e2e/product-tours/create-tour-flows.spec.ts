import { locateByDataAttr, randomString } from '../../utils'
import { expect, test } from '../../utils/playwright-test-base'

test.describe('Product Tours Toolbar', () => {
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
    })

    test('Can start new tour creation modal from product tours page', async ({ page }) => {
        const tourCreateButton = await locateByDataAttr(page, 'tour-type-selection-button__tour')
        await expect(tourCreateButton).toBeVisible()

        await tourCreateButton.click()

        await expect(page.getByText('Select a URL to launch the toolbar and create your product tour')).toBeVisible()
    })
    ;[{ presentation: 'modal' }, { presentation: 'banner' }].forEach(({ presentation }) => {
        test(`Can create ${presentation} announcement`, async ({ page }) => {
            const announcementCreateButton = await locateByDataAttr(page, 'tour-type-selection-button__announcement')
            await expect(announcementCreateButton).toBeVisible()

            await announcementCreateButton.click()

            const presentationSelectionButton = await locateByDataAttr(
                page,
                `announcement-presentation-select__${presentation}`
            )
            await expect(presentationSelectionButton).toBeVisible()
            await presentationSelectionButton.click()

            const tourName = `My ${presentation} announcement ${randomString()}`
            const titleInput = await locateByDataAttr(page, 'tour-announcement-title-input')
            await expect(titleInput).toBeVisible()
            titleInput.fill(tourName)
            ;(await locateByDataAttr(page, 'tour-announcement-create-button')).click()
            await expect(await locateByDataAttr(page, `announcement-content-editor__${presentation}`)).toBeVisible()
            ;(await locateByDataAttr(page, 'product-tour-action-btn__cancel')).click()
            ;(await locateByDataAttr(page, 'info-actions-panel')).click()
            ;(await locateByDataAttr(page, 'product-tour-panel-action-button__delete')).click()
            ;(await locateByDataAttr(page, 'product-tour-panel-action-button__confirm-delete')).click()

            const table = await locateByDataAttr(page, 'product-tours-table')
            await expect(table).toBeVisible()

            await expect(table.locator('td').getByText(tourName)).not.toBeVisible()
        })
    })
})
