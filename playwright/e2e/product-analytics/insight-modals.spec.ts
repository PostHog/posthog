import { InsightType } from '~/types'

import { InsightPage } from '../../page-models/insightPage'
import { randomString } from '../../utils'
import { disableAnimations } from '../../utils/pagePerformance'
import { expect, test } from '../../utils/playwright-test-base'

test.describe('insight modals', () => {
    test.beforeEach(async ({ page }) => {
        await disableAnimations(page)
    })

    // does not consistently load events 😡
    test.skip('shows no matches message in persons modal', async ({ page }) => {
        const insightPage = new InsightPage(page)
        await insightPage.createNew(randomString('insight-'), InsightType.TRENDS)
        await insightPage.openPersonsModal()
        await expect(page.locator('[data-attr="persons-modal-no-matches"]')).toBeVisible()
    })
})
