import { cleanup, fireEvent, render, screen } from '@testing-library/react'

import { SdkVersionStatusTag } from './SdkHealthComponents'

const STATUS_REASON = 'Released 2 years ago. Upgrade recommended.'

describe('SdkVersionStatusTag', () => {
    afterEach(() => {
        cleanup()
    })

    it('shows the status reason when the tag is clicked', async () => {
        render(
            <SdkVersionStatusTag type="danger" statusReason={STATUS_REASON}>
                Outdated
            </SdkVersionStatusTag>
        )

        expect(screen.queryByText(STATUS_REASON)).toBeNull()

        fireEvent.click(screen.getByText('Outdated'))

        expect(await screen.findByText(STATUS_REASON)).toBeTruthy()
    })

    it('is focusable so keyboard users can reach the status reason too', () => {
        render(
            <SdkVersionStatusTag type="success" statusReason={STATUS_REASON}>
                Current
            </SdkVersionStatusTag>
        )

        expect(screen.getByText('Current').getAttribute('tabindex')).toBe('0')
    })
})
