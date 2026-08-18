import { MOCK_DEFAULT_ORGANIZATION } from 'lib/api.mock'

import '@testing-library/jest-dom'

import { cleanup, fireEvent, render } from '@testing-library/react'
import { Provider } from 'kea'
import { router } from 'kea-router'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { aiConsentLogic } from './aiConsentLogic'
import { AIConsentPopoverWrapper } from './AIConsentPopoverWrapper'

describe('AIConsentPopoverWrapper pending redirect', () => {
    let logic: ReturnType<typeof aiConsentLogic.build>

    beforeEach(() => {
        localStorage.clear()
        useMocks({
            patch: {
                // Never resolves, so acceptDataProcessing stays pending and can't clear the redirect
                // before we read it back.
                '/api/organizations/:id': () => new Promise(() => {}),
            },
        })
        initKeaTests(true, undefined, undefined, {
            ...MOCK_DEFAULT_ORGANIZATION,
            is_ai_data_processing_approved: false,
        })
        logic = aiConsentLogic()
        logic.mount()
    })

    afterEach(() => {
        cleanup()
        logic?.unmount()
    })

    // An explicit pendingRedirectUrl must win over the current location, so the chat composer can
    // resume without its unsaved `?chat=` param (which would walk the user back onto the
    // "Conversation not found" page).
    it('persists an explicit pendingRedirectUrl for replay after the reauthentication redirect', () => {
        router.actions.push('/ai?chat=unsaved-id')
        render(
            <Provider>
                <AIConsentPopoverWrapper ignoreDismissal pendingRedirectUrl="/ai">
                    <button>send</button>
                </AIConsentPopoverWrapper>
            </Provider>
        )

        fireEvent.click(document.querySelector('[data-attr="ai-consent-approve"]')!)
        // Legal dialog confirm — its onClick fires the wrapper's approve handler synchronously.
        fireEvent.click(document.querySelector('[data-attr="ai-consent-legal-confirm"]')!)

        expect(logic.values.pendingApprovalRedirect?.url).toBe('/ai')
    })
})
