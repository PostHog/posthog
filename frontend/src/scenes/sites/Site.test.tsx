import '@testing-library/jest-dom'

import { render } from '@testing-library/react'
import { Provider } from 'kea'

import {
    AuthorizedUrlListType,
    authorizedUrlListLogic,
    defaultAuthorizedUrlProperties,
} from 'lib/components/AuthorizedUrlList/authorizedUrlListLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { Site } from './Site'

describe('Site preview scene', () => {
    beforeEach(() => {
        useMocks({
            post: {
                '/api/environments/:team_id/query/': [200, { results: [] }],
            },
        })
        initKeaTests()
        const logic = authorizedUrlListLogic({
            ...defaultAuthorizedUrlProperties,
            type: AuthorizedUrlListType.TOOLBAR_URLS,
        })
        logic.mount()
        // Deterministic authorized list, independent of mock-team load timing
        logic.actions.setAuthorizedUrls(['https://example.com', 'https://*.allowed.com'])
    })

    const renderSite = (url: string): HTMLElement => {
        const { container } = render(
            <Provider>
                <Site url={url} />
            </Provider>
        )
        return container
    }

    it('renders the preview iframe for an authorized https URL', () => {
        const iframe = renderSite('https://example.com').querySelector('iframe')
        expect(iframe).not.toBeNull()
        expect(iframe?.getAttribute('src')).toContain('https://example.com')
    })

    it('renders the preview iframe for an authorized wildcard subdomain', () => {
        const iframe = renderSite('https://app.allowed.com').querySelector('iframe')
        expect(iframe).not.toBeNull()
    })

    it.each([
        ['javascript: scheme', 'javascript:alert(document.domain)//'],
        ['data: scheme', 'data:text/html,<script>alert(1)</script>'],
        ['vbscript: scheme', 'vbscript:msgbox(1)'],
        ['unauthorized https origin', 'https://evil.example.net'],
        ['empty url', ''],
    ])('does not render an iframe for %s', (_label, url) => {
        const iframe = renderSite(url).querySelector('iframe')
        expect(iframe).toBeNull()
    })
})
