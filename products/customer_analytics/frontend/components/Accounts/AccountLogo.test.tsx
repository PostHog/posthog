import '@testing-library/jest-dom'

import { cleanup, fireEvent, render } from '@testing-library/react'
import { Provider } from 'kea'

import { initKeaTests } from '~/test/init'

import { AccountLogo } from './AccountLogo'

describe('AccountLogo', () => {
    const originalJsUrl = window.JS_URL

    beforeEach(() => {
        initKeaTests()
        window.JS_URL = 'https://assets.example.com/static'
    })

    afterEach(() => {
        cleanup()
        window.JS_URL = originalJsUrl
    })

    it('tries the CDN favicon, then the logo.dev proxy, then shows the lettermark', () => {
        const { container } = render(
            <Provider>
                <AccountLogo domain="acme.example" name="Acme" />
            </Provider>
        )

        const cdnImage = container.querySelector('img')
        expect(cdnImage).toHaveAttribute('src', 'https://assets.example.com/static/favicons/acme.example')

        fireEvent.error(cdnImage!)
        const proxyImage = container.querySelector('img')
        expect(proxyImage?.getAttribute('src')).toMatch(/\/accounts\/icon\/\?domain=acme\.example&theme=light$/)

        fireEvent.error(proxyImage!)
        expect(container.querySelector('img')).toBeNull()
    })

    it('goes straight to the proxy when no static CDN is configured', () => {
        window.JS_URL = undefined
        const { container } = render(
            <Provider>
                <AccountLogo domain="acme.example" name="Acme" />
            </Provider>
        )

        expect(container.querySelector('img')?.getAttribute('src')).toMatch(/\/accounts\/icon\/\?domain=acme\.example/)
    })
})
