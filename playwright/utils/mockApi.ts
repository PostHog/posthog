import { Page } from '@playwright/test'

export function decideResponse(featureFlags: Record<string, any>): Record<string, any> {
    return {
        config: {
            enable_collect_everything: true,
        },
        toolbarParams: {
            toolbarVersion: 'toolbar',
        },
        isAuthenticated: true,
        supportedCompression: ['gzip', 'gzip-js', 'lz64'],
        hasFeatureFlags: Object.keys(featureFlags).length > 0,
        featureFlags,
        sessionRecording: {
            endpoint: '/s/',
        },
    }
}

export const mockFeatureFlags = async (page: Page, overrides: Record<string, any>): Promise<void> => {
    // Tricky - the new RemoteConfig endpoint is optimised to not load decide if there are no feature flags in the DB.
    // We need to intercept both the RemoteConfig and the decide endpoint to ensure that the feature flags are always loaded.

    await page.route('**/array/*/config', async (route) => {
        await route.fulfill({
            status: 200,
            body: JSON.stringify({
                ...decideResponse(overrides),
            }),
        })
    })

    await page.route('**/array/*/config.js', async (route) => {
        await route.continue()
    })

    await page.route('**/flags/*', async (route) => {
        await route.fulfill({
            status: 200,
            body: JSON.stringify({
                ...decideResponse(overrides),
            }),
        })
    })
}
