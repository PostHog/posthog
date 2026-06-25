import { ToolbarParams } from '~/types'

// Keep the real toolbar posthog-js instance (rendering depends on it) but spy on
// the exception capture helper so we can assert what does and doesn't get reported.
jest.mock('~/toolbar/toolbarPosthogJS', () => ({
    ...jest.requireActual('~/toolbar/toolbarPosthogJS'),
    captureToolbarException: jest.fn(),
}))

// Mock window and fetch
const mockFetch = jest.fn()

describe('Toolbar flag loading', () => {
    beforeEach(() => {
        // Assigned per-test: the MSW harness's beforeAll (src/mocks/jest.ts) replaces
        // global.fetch after module evaluation, so a module-level assignment is clobbered.
        global.fetch = mockFetch
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

        expect(mockPostHog.featureFlags.overrideFeatureFlags).not.toHaveBeenCalled()

        consoleErrorSpy.mockRestore()
    })

    it.each([
        {
            name: 'transient network failure (fetch rejects)',
            // `fetch` rejects only on network-level failures — these should be logged, not captured.
            setupMock: () => mockFetch.mockRejectedValueOnce(new TypeError('Failed to fetch')),
            expectCapture: false,
        },
        {
            name: 'unexpected error while applying flags (TypeError thrown in processing)',
            // A null body makes `data.featureFlags` throw a TypeError during processing —
            // a genuine bug that must still reach error tracking.
            setupMock: () => mockFetch.mockResolvedValueOnce({ json: async () => null }),
            expectCapture: true,
        },
    ])('reports only genuine errors as exceptions: $name', async ({ setupMock, expectCapture }) => {
        const consoleErrorSpy = jest.spyOn(console, 'error').mockImplementation()
        const consoleWarnSpy = jest.spyOn(console, 'warn').mockImplementation()

        await import('./index')
        const { captureToolbarException } = await import('~/toolbar/toolbarPosthogJS')

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

        setupMock()

        await (window as any).ph_load_toolbar(toolbarParams, mockPostHog)

        if (expectCapture) {
            expect(captureToolbarException).toHaveBeenCalledWith(expect.anything(), 'preloaded_flags_fetch')
        } else {
            expect(captureToolbarException).not.toHaveBeenCalled()
            expect(consoleWarnSpy).toHaveBeenCalled()
        }

        consoleErrorSpy.mockRestore()
        consoleWarnSpy.mockRestore()
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
