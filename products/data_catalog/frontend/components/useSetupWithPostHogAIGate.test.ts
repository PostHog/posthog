import { MOCK_DEFAULT_ORGANIZATION } from 'lib/api.mock'

import { act, renderHook } from '@testing-library/react'
import posthog from 'posthog-js'

import { organizationLogic } from 'scenes/organizationLogic'

import { initKeaTests } from '~/test/init'

import { catalogSetupLogic } from '../catalogSetupLogic'
import { useSetupWithPostHogAIGate } from './useSetupWithPostHogAIGate'

function setConsent(approved: boolean): void {
    organizationLogic.actions.loadCurrentOrganizationSuccess({
        ...MOCK_DEFAULT_ORGANIZATION,
        is_ai_data_processing_approved: approved,
    })
}

describe('useSetupWithPostHogAIGate', () => {
    beforeEach(() => {
        initKeaTests()
        setConsent(false)
    })

    test.each([
        // Consent turns on while the popover is open, before `onApprove` runs. Resuming then starts setup twice.
        ['the person approves in the popover', 'popover'],
        ['an SSO reauthentication reloaded the page during approval', 'reload'],
    ])('when %s, setup starts once', (_, flow) => {
        const capture = jest.spyOn(posthog, 'capture')
        catalogSetupLogic.mount()
        if (flow === 'reload') {
            catalogSetupLogic.actions.rememberSetupIntent('banner')
        }
        const { result } = renderHook(() => useSetupWithPostHogAIGate('banner'))

        if (flow === 'popover') {
            act(() => result.current.onClick())
            act(() => result.current.popover.onBeforeApprove?.())
        }
        act(() => setConsent(true))
        if (flow === 'popover') {
            act(() => result.current.popover.onApprove())
        }

        const starts = capture.mock.calls.filter(([event]) => event === 'data catalog setup with ai started')
        expect(starts).toHaveLength(1)
    })
})
