import { render, within } from '@testing-library/react'

import { lemonToast } from '@posthog/lemon-ui'

import { CHANGE_REQUEST_PENDING_CODE, showApprovalRequiredToast } from './ApprovalRequiredBanner'

describe('showApprovalRequiredToast', () => {
    let infoSpy: jest.SpyInstance

    beforeEach(() => {
        infoSpy = jest.spyOn(lemonToast, 'info').mockImplementation()
    })

    it.each([
        { code: undefined, expected: 'Your request to enable this flag has been submitted for approval.' },
        { code: 'approval_required', expected: 'Your request to enable this flag has been submitted for approval.' },
        { code: CHANGE_REQUEST_PENDING_CODE, expected: 'A request to enable this flag is already pending approval.' },
    ])('renders "$expected" for code=$code', ({ code, expected }) => {
        showApprovalRequiredToast('cr-1', 'enable this flag', code)

        const [message, options] = infoSpy.mock.calls[0]
        expect(options).toEqual({ toastId: 'approval-required-cr-1' })
        const { container } = render(message)
        expect(within(container).getByText(expected)).toBeTruthy()
    })
})
