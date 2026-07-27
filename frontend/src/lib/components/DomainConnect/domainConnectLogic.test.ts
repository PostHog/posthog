import { lemonToast } from 'lib/lemon-ui/LemonToast'

import { initKeaTests } from '~/test/init'

import { domainConnectLogic } from './domainConnectLogic'

describe('domainConnectLogic', () => {
    let successSpy: jest.SpyInstance
    let errorSpy: jest.SpyInstance

    beforeEach(() => {
        initKeaTests()
        successSpy = jest.spyOn(lemonToast, 'success').mockReturnValue('' as any)
        errorSpy = jest.spyOn(lemonToast, 'error').mockReturnValue('' as any)
    })

    afterEach(() => {
        successSpy.mockRestore()
        errorSpy.mockRestore()
        window.history.replaceState({}, '', '/')
    })

    // afterMount reads the redirect params off the real window.location, so drive it there.
    const mountReturningWith = (search: string): ReturnType<typeof domainConnectLogic> => {
        window.history.replaceState({}, '', `/settings${search}`)
        const logic = domainConnectLogic({ logicKey: 'test', domain: null, context: 'proxy' })
        logic.mount()
        return logic
    }

    it('shows a success toast when the provider returns without an error', () => {
        const logic = mountReturningWith('?domain_connect=proxy')

        expect(successSpy).toHaveBeenCalledTimes(1)
        expect(errorSpy).not.toHaveBeenCalled()

        logic.unmount()
    })

    it('surfaces the provider error instead of a false success when the apply fails', () => {
        const logic = mountReturningWith(
            '?domain_connect=proxy&error=server_error&error_description=Unable+to+edit+this+record'
        )

        expect(errorSpy).toHaveBeenCalledTimes(1)
        expect(errorSpy).toHaveBeenCalledWith(expect.stringContaining('Unable to edit this record'))
        expect(successSpy).not.toHaveBeenCalled()

        logic.unmount()
    })

    it('does not toast when returning for a different context', () => {
        const logic = mountReturningWith('?domain_connect=email')

        expect(successSpy).not.toHaveBeenCalled()
        expect(errorSpy).not.toHaveBeenCalled()

        logic.unmount()
    })
})
