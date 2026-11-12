import '@testing-library/jest-dom'

import { act, cleanup, render } from '@testing-library/react'
import { Provider } from 'kea'

import { initKeaTests } from '~/test/init'

import { loginLogic } from '../loginLogic'
import { LoginTurnstileWidget } from './LoginTurnstileWidget'

let mockTurnstileProps: Record<string, any> = {}

jest.mock('@marsidev/react-turnstile', () => ({
    Turnstile: (props: Record<string, any>) => {
        mockTurnstileProps = props
        return null
    },
}))

describe('LoginTurnstileWidget', () => {
    let logic: ReturnType<typeof loginLogic.build>

    beforeEach(() => {
        jest.useFakeTimers()
        mockTurnstileProps = {}
        initKeaTests()
        logic = loginLogic()
        logic.mount()
    })

    afterEach(() => {
        cleanup()
        logic.unmount()
        jest.useRealTimers()
        delete (window as any).turnstile
    })

    function renderWidget(): ReturnType<typeof render> {
        return render(
            <Provider>
                <LoginTurnstileWidget siteKey="site" />
            </Provider>
        )
    }

    it('runs a silent login widget and starts as pending', () => {
        const { container } = renderWidget()

        expect(mockTurnstileProps.siteKey).toEqual('site')
        expect(mockTurnstileProps.options).toMatchObject({ action: 'login', appearance: 'interaction-only' })
        expect(logic.values.turnstileClientStatus).toEqual('pending')
        expect(container).toHaveTextContent('')
    })

    it('marks script_failed when the script has not loaded after 10 seconds', () => {
        renderWidget()

        act(() => jest.advanceTimersByTime(9_999))
        expect(logic.values.turnstileClientStatus).toEqual('pending')
        act(() => jest.advanceTimersByTime(1))
        expect(logic.values.turnstileClientStatus).toEqual('script_failed')
    })

    it('marks script_failed after 10 seconds when the script tag exists but the Turnstile API never arrives', () => {
        renderWidget()

        act(() => mockTurnstileProps.onLoadScript?.())
        act(() => jest.advanceTimersByTime(10_000))

        expect(logic.values.turnstileClientStatus).toEqual('script_failed')
    })

    it('stays pending after 10 seconds once the Turnstile API is on the page', () => {
        renderWidget()

        ;(window as any).turnstile = {}
        act(() => jest.advanceTimersByTime(10_000))

        expect(logic.values.turnstileClientStatus).toEqual('pending')
    })

    it('keeps script_failed when the widget remounts after a script error', () => {
        const { unmount } = renderWidget()
        act(() => mockTurnstileProps.scriptOptions.onError())
        unmount()

        renderWidget()

        expect(logic.values.turnstileClientStatus).toEqual('script_failed')
    })

    it('stores the token on success', () => {
        renderWidget()

        act(() => mockTurnstileProps.onSuccess('tok'))

        expect(logic.values.turnstileToken).toEqual('tok')
        expect(logic.values.turnstileClientStatus).toEqual('token')
    })

    it.each([
        ['onError', 'error'],
        ['onTimeout', 'error'],
        ['onExpire', 'expired'],
        ['onUnsupported', 'unsupported'],
    ])('drops the token and reports %s as %s, with no visible error', (callback, status) => {
        const { container } = renderWidget()
        act(() => mockTurnstileProps.onSuccess('tok'))

        act(() => mockTurnstileProps[callback]())

        expect(logic.values.turnstileToken).toBeNull()
        expect(logic.values.turnstileClientStatus).toEqual(status)
        expect(container).toHaveTextContent('')
    })

    it('marks script_failed at once when the script fails to load', () => {
        renderWidget()

        act(() => mockTurnstileProps.scriptOptions.onError())

        expect(logic.values.turnstileClientStatus).toEqual('script_failed')
    })

    it('reports not_rendered and drops the token when it unmounts', () => {
        const { unmount } = renderWidget()
        act(() => mockTurnstileProps.onSuccess('tok'))

        unmount()

        expect(logic.values.turnstileToken).toBeNull()
        expect(logic.values.turnstileClientStatus).toEqual('not_rendered')
    })
})
