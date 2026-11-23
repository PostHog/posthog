import '@testing-library/jest-dom'

import { cleanup, render, waitFor } from '@testing-library/react'
import { Provider } from 'kea'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { preflightLogic } from 'lib/logic/preflightLogic'

import preflightJson from '~/mocks/fixtures/_preflight.json'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { SocialLoginButtons } from './SocialLoginButton'

describe('SocialLoginButtons', () => {
    beforeEach(() => {
        useMocks({
            get: {
                '/_preflight': () => [
                    200,
                    { ...preflightJson, available_social_auth_providers: { github: true, chatgpt: true } },
                ],
            },
        })
        initKeaTests()
        preflightLogic.mount()
        featureFlagLogic.mount()
    })

    afterEach(() => {
        cleanup()
    })

    test.each([
        { flagEnabled: false, expectedLinks: ['/login/github/'] },
        { flagEnabled: true, expectedLinks: ['/login/github/', '/login/chatgpt/'] },
    ])(
        'renders the ChatGPT button only behind its flag (flag enabled: $flagEnabled)',
        async ({ flagEnabled, expectedLinks }) => {
            featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.SIGN_IN_WITH_CHATGPT]: flagEnabled })
            const { container } = render(
                <Provider>
                    <SocialLoginButtons />
                </Provider>
            )

            await waitFor(() => {
                const links = Array.from(container.querySelectorAll('a')).map((link) => link.getAttribute('href'))
                expect(links).toEqual(expectedLinks)
            })
        }
    )
})
