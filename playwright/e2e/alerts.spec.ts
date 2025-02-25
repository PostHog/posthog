import { expect, test } from '../utils/playwright-test-base'

test.describe('Alerts', () => {
    test.beforeEach(async ({ page }) => {
        // This is conceptually like setupFeatureFlags({ alerts: true }) + createInsight('insight')
        // Replace with your own actual steps:
        // e.g. enabling feature flags or creating an insight
        await page.goto('/insights') // or wherever you create the insight
        await page.click('text=New insight')
        await page.fill('[data-attr="insight-name"]', 'insight')
        await page.click('[data-attr="insight-save-button"]')
        await page.waitForURL(/insights\/.*/)
        // Then go to the place where alerts are visible
    })

    async function createAlert(
        page,
        name = 'Alert name',
        lowerThreshold = '100',
        upperThreshold = '200',
        condition?: string
    ): Promise<void> {
        await page.click('text=Alerts')
        await page.click('text=New alert')

        await page.fill('[data-attr=alertForm-name]', name)
        await page.click('[data-attr=subscribed-users]')
        // pick some user or "self" from the dropdown
        await page.keyboard.press('ArrowDown')
        await page.keyboard.press('Enter')

        if (condition) {
            await page.click('[data-attr=alertForm-condition]')
            await page.click(`text=${condition}`)
            // for the "percent" part
            await page.click('text=%')
        }

        await page.fill('[data-attr=alertForm-lower-threshold]', lowerThreshold)
        await page.fill('[data-attr=alertForm-upper-threshold]', upperThreshold)
        await page.click('text=Create alert')
        await expect(page.locator('.Toastify__toast-body')).toContainText('Alert created.')
        await expect(page).toHaveURL(/(?<!\/new)$/) // ensure it navigates away
        await expect(page.locator('[data-attr=alert-list-item]').locator(`text=${name}`)).toBeVisible()

        // close side panel
        await page.click('text=Close')
    }

    async function setInsightDisplayTypeAndSave(page, displayType: string): Promise<void> {
        await page.click('[data-attr=insight-edit-button]')
        await page.click('[data-attr=chart-filter]')
        await page.click(`text=${displayType}`)
        await page.click('[data-attr=insight-save-button] >> text=Save')
        await expect(page).not.toHaveURL(/edit/)
    }

    test('Should allow create and delete an alert', async ({ page }) => {
        // Alerts disabled for trends with graphs
        await expect(page.locator('text=Alerts')).toHaveAttribute('aria-disabled', 'true')

        await setInsightDisplayTypeAndSave(page, 'Number')

        await createAlert(page)
        await page.reload()

        // check the alert
        await page.click('text=Alerts')
        await page.locator('[data-attr=alert-list-item]').locator('text=Alert name').click()

        await expect(page.locator('[data-attr=alertForm-name]')).toHaveValue('Alert name')
        await expect(page.locator('[data-attr=alertForm-lower-threshold]')).toHaveValue('100')
        await expect(page.locator('[data-attr=alertForm-upper-threshold]')).toHaveValue('200')

        await page.click('text=Delete alert')
        await page.waitForTimeout(2000) // or replace with a wait for toast or request

        await page.reload()
        await expect(page.locator('text=Alert name')).toHaveCount(0)
    })

    test('Should warn about alert deletion if changing the underlying insight type', async ({ page }) => {
        await setInsightDisplayTypeAndSave(page, 'Area chart')
        await createAlert(page, 'Alert to be deleted because of a changed insight')

        // now change insight type
        await page.click('[data-attr=insight-edit-button]')
        await page.click('text=Funnels')

        await expect(page.locator('text=the existing alerts will be deleted')).toBeVisible()

        // revert
        await page.click('text=Trends')
        await expect(page.locator('text=the existing alerts will be deleted')).toHaveCount(0)

        // confirm
        await page.click('text=Funnels')
        await page.locator('[data-attr=insight-save-button] >> text=Save').click()

        await page.click('text=Alerts')
        await expect(page.locator('text=Alert to be deleted because of a changed insight')).toHaveCount(0)
    })

    test('Should allow create and delete a relative alert', async ({ page }) => {
        // Alerts disabled for trends with graphs
        await expect(page.locator('text=Alerts')).toHaveAttribute('aria-disabled', 'true')

        await setInsightDisplayTypeAndSave(page, 'Bar chart')

        await createAlert(page, 'Alert name', '10', '20', 'increases by')
        await page.reload()

        // check the alert
        await page.click('text=Alerts')
        await page.locator('[data-attr=alert-list-item]').locator('text=Alert name').click()
        await expect(page.locator('[data-attr=alertForm-name]')).toHaveValue('Alert name')
        await expect(page.locator('[data-attr=alertForm-lower-threshold]')).toHaveValue('10')
        await expect(page.locator('[data-attr=alertForm-upper-threshold]')).toHaveValue('20')

        await page.click('text=Delete alert')
        await page.waitForTimeout(2000)

        await page.reload()
        await expect(page.locator('text=Alert name')).toHaveCount(0)
    })

    test('Should allow creating alerts on trends with breakdowns', async ({ page }) => {
        // This was `createInsightWithBreakdown('insight with breakdown')`
        // For brevity, do a short version:
        await page.click('text=New insight')
        await page.click('text=Add breakdown')
        await page.click('text=Browser') // or so
        await page.click('[data-attr="insight-save-button"]')

        await setInsightDisplayTypeAndSave(page, 'Bar chart')
        await createAlert(page, 'Alert name', '10', '20', 'increases by')
        await page.reload()

        await page.click('text=Alerts')
        await page.locator('[data-attr=alert-list-item]').locator('text=Alert name').click()
        await expect(page.locator('text=any breakdown value')).toBeVisible()
        await expect(page.locator('[data-attr=alertForm-name]')).toHaveValue('Alert name')

        await page.click('text=Delete alert')
        await page.waitForTimeout(2000)

        await page.reload()
        await expect(page.locator('text=Alert name')).toHaveCount(0)
    })
})
