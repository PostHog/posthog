import { expect, test } from '../utils/playwright-test-base'

test.describe('PostHog AI', () => {
    test.beforeEach(async ({ page }) => {
        // Check if the AI sidepanel button is available (requires artificial-hog feature flag)
        const sidepanelButton = page.locator('[data-attr="sidepanel-tab-max"]')

        try {
            // Wait for the button to appear with a reasonable timeout
            await sidepanelButton.waitFor({ state: 'visible', timeout: 15000 })
        } catch {
            // If button doesn't appear, skip the test
            test.skip(true, 'AI feature (artificial-hog flag) is not enabled for this user')
            return
        }

        // Open the AI side panel
        await sidepanelButton.click()
    })

    test('See AI interface', async ({ page }) => {
        // Verify the AI intro/welcome screen is visible (using a more specific heading)
        await expect(page.getByRole('heading', { name: /Try PostHog AI/ })).toBeVisible()

        // Verify the question input is visible
        await expect(page.getByPlaceholder('Ask away (/ for commands)')).toBeVisible()
    })

    test('Ask a question and receive answer', async ({ page }) => {
        // Type a very specific prompt that should get an exact response
        const questionInput = page.getByPlaceholder('Ask away (/ for commands)')
        await questionInput.click()
        await questionInput.fill("Output just the word 'Cześć' and nothing else")

        // Submit the question by pressing Enter
        await questionInput.press('Enter')

        // Wait for the question to appear in the thread
        await expect(
            page.locator('[data-message-type="human"]').getByText("Output just the word 'Cześć' and nothing else")
        ).toBeVisible()

        // Wait for AI to respond with exactly "Cześć"
        await expect(page.locator('[data-message-type="ai"]').getByText('Cześć')).toBeVisible({ timeout: 30000 })
    })

    test('Input field states', async ({ page }) => {
        const questionInput = page.getByPlaceholder('Ask away (/ for commands)')

        // Input should be enabled initially
        await expect(questionInput).toBeEnabled()

        // Type a question
        await questionInput.fill('Test question')

        // Verify the text appears
        await expect(questionInput).toHaveValue('Test question')

        // Submit
        await questionInput.press('Enter')

        // After submission, placeholder should change to "Thinking…"
        await expect(page.getByPlaceholder('Thinking…')).toBeVisible({ timeout: 5000 })
    })
})
