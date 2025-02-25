import { randomString } from '../utils'
import { expect, test } from '../utils/playwright-test-base'

test.describe('Invite Signup', () => {
    test('Authenticated user can invite user', async ({ page }) => {
        const userPrefix = randomString('user-charlie-')
        const email = `${userPrefix}@posthog.com`

        // go to org settings
        await page.locator('[data-attr=menu-item-me]').click()
        await page.locator('[data-attr=top-menu-item-org-settings]').click()
        await expect(page).toHaveURL(/settings\/organization/)

        // create invite
        await page.click('[data-attr=invite-teammate-button]')
        await page.fill('[data-attr=invite-email-input]', email)
        await page.click('[data-attr=invite-team-member-submit]')
        await expect(page.locator('[data-attr=invites-table]')).toContainText(email)

        // attempt to use the invite link for a different email => see error
        const inviteLink = await page
            .locator('[data-attr=invites-table] tbody tr:last-of-type td:nth-last-child(2)')
            .innerText()
        await page.goto(inviteLink)
        await expect(page.locator('h2')).toContainText("Oops! This invite link can't be used")
        await expect(page.locator('.error-message div')).toContainText(
            'This invite is intended for another email address'
        )

        // Delete the invite
        await page.goto('/organization/members')
        await page.locator('[data-attr=invites-table]').locator('[data-attr=invite-delete]').first().click()
        await page.locator('.LemonModal .LemonButton', { hasText: 'Yes, cancel invite' }).click()
        await expect(page.locator('.Toastify__toast-body')).toContainText(`Invite for ${email} has been canceled`)
        await expect(page.locator('[data-attr=invites-table]')).not.toContainText(email)
    })

    // Additional test verifying the new user can sign up with the link, etc.
})
