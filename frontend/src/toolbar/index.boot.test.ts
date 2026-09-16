describe('toolbar entry boot', () => {
    let hasOwnAtToolbarEvaluation: string

    beforeEach(() => {
        jest.resetModules()
        hasOwnAtToolbarEvaluation = 'unknown'
        jest.doMock('~/toolbar/ToolbarApp', () => {
            hasOwnAtToolbarEvaluation = typeof Object.hasOwn
            return { ToolbarApp: () => null }
        })
    })

    afterEach(() => {
        delete (window as { ph_load_toolbar?: unknown }).ph_load_toolbar
        jest.restoreAllMocks()
    })

    it('shims Object.hasOwn before the toolbar chunk evaluates on a pre-ES2022 engine', async () => {
        const nativeHasOwn = Object.hasOwn
        Reflect.deleteProperty(Object, 'hasOwn')

        try {
            await jest.isolateModulesAsync(async () => {
                await import('./index')
            })

            expect(hasOwnAtToolbarEvaluation).toBe('function')
            expect(Object.hasOwn({ present: undefined }, 'present')).toBe(true)
            expect(Object.hasOwn({}, 'absent')).toBe(false)
            expect(typeof (window as { ph_load_toolbar?: unknown }).ph_load_toolbar).toBe('function')
        } finally {
            Object.defineProperty(Object, 'hasOwn', { value: nativeHasOwn, writable: true, configurable: true })
        }
    })
})
