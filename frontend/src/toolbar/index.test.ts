import { ToolbarParams } from '~/types'

// Mock window and fetch
const mockFetch = jest.fn()
global.fetch = mockFetch

describe('Toolbar flag loading', () => {
    beforeEach(() => {
        jest.clearAllMocks()
        mockFetch.mockClear()
        jest.resetModules()

        // Setup DOM
        document.body.innerHTML = ''

        // Mock window.ph_load_toolbar
        delete (window as any).ph_load_toolbar
    })

    it('should fetch feature flags when toolbarFlagsKey is present', async () => {
        // Import the module to register ph_load_toolbar
        await import('./index')

        const mockPostHog = {
            featureFlags: {
                overrideFeatureFlags: jest.fn(),
                reloadFeatureFlags: jest.fn(),
            },
        }

        const toolbarParams: ToolbarParams = {
            apiURL: 'http://localhost:8010',
            toolbarFlagsKey: 'test-key-123',
            token: 'test-token',
        }

        const mockFlags = {
            'flag-1': true,
            'flag-2': 'variant-a',
            'flag-3': false,
        }

        mockFetch.mockResolvedValueOnce({
            ok: true,
            json: async () => ({ featureFlags: mockFlags }),
        })

        // Call ph_load_toolbar
        await (window as any).ph_load_toolbar(toolbarParams, mockPostHog)

        // Verify fetch was called with correct URL
        expect(mockFetch).toHaveBeenCalledWith(
            'http://localhost:8010/api/user/get_toolbar_preloaded_flags?key=test-key-123',
            {
                credentials: 'include',
            }
        )

        // Verify flags were applied to posthog instance with correct format
        expect(mockPostHog.featureFlags.overrideFeatureFlags).toHaveBeenCalledWith({ flags: mockFlags })
    })

    it('should handle fetch errors gracefully', async () => {
        const consoleErrorSpy = jest.spyOn(console, 'error').mockImplementation()

        await import('./index')

        const mockPostHog = {
            featureFlags: {
                overrideFeatureFlags: jest.fn(),
            },
        }

        const toolbarParams: ToolbarParams = {
            apiURL: 'http://localhost:8010',
            toolbarFlagsKey: 'test-key-123',
            token: 'test-token',
        }

        mockFetch.mockRejectedValueOnce(new Error('Network error'))

        // Should not throw
        await (window as any).ph_load_toolbar(toolbarParams, mockPostHog)

        expect(consoleErrorSpy).toHaveBeenCalledWith(
            '[Toolbar Flags] Error fetching toolbar feature flags:',
            expect.any(Error)
        )

        // Should not have called overrideFeatureFlags
        expect(mockPostHog.featureFlags.overrideFeatureFlags).not.toHaveBeenCalled()

        consoleErrorSpy.mockRestore()
    })

    it('should handle non-ok responses gracefully', async () => {
        const consoleErrorSpy = jest.spyOn(console, 'error').mockImplementation()

        await import('./index')

        const mockPostHog = {
            featureFlags: {
                overrideFeatureFlags: jest.fn(),
            },
        }

        const toolbarParams: ToolbarParams = {
            apiURL: 'http://localhost:8010',
            toolbarFlagsKey: 'test-key-123',
            token: 'test-token',
        }

        const error = { ok: false, statusText: 'Not Found' }
        mockFetch.mockResolvedValueOnce({
            json() {
                return Promise.resolve(error)
            },
        })

        await (window as any).ph_load_toolbar(toolbarParams, mockPostHog)

        expect(consoleErrorSpy).toHaveBeenCalledWith('[Toolbar Flags] Feature flags not found:', JSON.stringify(error))

        expect(mockPostHog.featureFlags.overrideFeatureFlags).not.toHaveBeenCalled()

        consoleErrorSpy.mockRestore()
    })

    it('should not fetch flags when toolbarFlagsKey is not present', async () => {
        await import('./index')

        const mockPostHog = {
            featureFlags: {
                overrideFeatureFlags: jest.fn(),
            },
        }

        const toolbarParams: ToolbarParams = {
            apiURL: 'http://localhost:8010',
            token: 'test-token',
            // No toolbarFlagsKey
        }

        await (window as any).ph_load_toolbar(toolbarParams, mockPostHog)

        // Should not have fetched flags
        expect(mockFetch).not.toHaveBeenCalled()
        expect(mockPostHog.featureFlags.overrideFeatureFlags).not.toHaveBeenCalled()
    })

    it('should still load toolbar even if flag fetching fails', async () => {
        await import('./index')

        const mockPostHog = {
            featureFlags: {
                overrideFeatureFlags: jest.fn(),
            },
        }

        const toolbarParams: ToolbarParams = {
            apiURL: 'http://localhost:8010',
            toolbarFlagsKey: 'test-key-123',
            token: 'test-token',
        }

        mockFetch.mockRejectedValueOnce(new Error('Network error'))

        // Should not throw - toolbar should still load
        await expect((window as any).ph_load_toolbar(toolbarParams, mockPostHog)).resolves.not.toThrow()

        // Verify toolbar container was created
        const container = document.querySelector('div')
        expect(container).toBeTruthy()
    })
})
