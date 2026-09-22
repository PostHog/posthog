import { mountSupportRouter } from './mountSupportRouter'

const mount = jest.fn()
let importError: Error | null = null

jest.mock('lib/components/Support/supportRouterLogic', () => ({
    get supportRouterLogic() {
        if (importError) {
            throw importError
        }
        return { mount }
    },
}))

describe('mountSupportRouter', () => {
    beforeEach(() => {
        importError = null
        mount.mockReset().mockReturnValue(jest.fn())
        jest.spyOn(console, 'warn').mockImplementation(() => {})
    })

    afterEach(() => {
        jest.restoreAllMocks()
    })

    it('mounts the router and unmounts it again', async () => {
        const unmountRouter = jest.fn()
        mount.mockReturnValue(unmountRouter)

        const { unmount, mounted } = mountSupportRouter()
        await mounted

        expect(mount).toHaveBeenCalledTimes(1)
        unmount()
        expect(unmountRouter).toHaveBeenCalledTimes(1)
    })

    it('unmounts a router that resolves after the caller disposed', async () => {
        const unmountRouter = jest.fn()
        mount.mockReturnValue(unmountRouter)

        const { unmount, mounted } = mountSupportRouter()
        unmount()
        await mounted

        expect(mount).toHaveBeenCalledTimes(1)
        expect(unmountRouter).toHaveBeenCalledTimes(1)
    })

    it.each([
        ['Firefox', 'error loading dynamically imported module: https://app/chunk.js'],
        ['esbuild', 'Failed to fetch dynamically imported module'],
        ['WebKit', 'Importing a module script failed.'],
    ])('swallows a %s chunk-load failure instead of rejecting', async (_browser, message) => {
        importError = new TypeError(message)

        const { unmount, mounted } = mountSupportRouter()
        await expect(mounted).resolves.toBeUndefined()

        expect(console.warn).toHaveBeenCalled()
        expect(() => unmount()).not.toThrow()
    })

    it('rethrows an error that is not a chunk-load failure', async () => {
        importError = new Error('supportRouterLogic is broken')

        const { mounted } = mountSupportRouter()
        await expect(mounted).rejects.toThrow('supportRouterLogic is broken')
    })
})
