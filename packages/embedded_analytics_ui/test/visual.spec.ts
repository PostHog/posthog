import { test, expect } from '@playwright/test'

test.describe('PostHog Analytics Components', () => {
    test('complete dashboard renders correctly', async ({ page }) => {
        // Navigate to the dashboard story
        await page.goto('/iframe.html?args=&id=analytics-overview--complete-dashboard&viewMode=story')

        // Wait for components to load
        await page.waitForSelector('.analytics-metric-card', { timeout: 10000 })

        // Wait for animations to settle and content to stabilize
        await page.waitForTimeout(2000)

        // Disable animations for stable screenshots
        await page.addStyleTag({
            content: `
        *, *::before, *::after {
          animation-duration: 0s !important;
          animation-delay: 0s !important;
          transition-duration: 0s !important;
          transition-delay: 0s !important;
        }
      `,
        })

        // Take screenshot of the entire dashboard
        await expect(page).toHaveScreenshot('dashboard-light.png', {
            fullPage: true,
            threshold: 0.2, // Allow small differences
        })
    })
})
