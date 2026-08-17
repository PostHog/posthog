import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { initKeaTests } from '~/test/init'

import { ErrorTrackingStackFrame } from '../types'
import { FrameDropDownMenu } from './FrameDropDownMenu'

const addressOnlyFrame: ErrorTrackingStackFrame = {
    raw_id: 'address-only',
    mangled_name: '',
    line: null,
    column: null,
    source: null,
    in_app: false,
    resolved_name: null,
    lang: 'swift',
    resolved: false,
    resolve_failure: 'No matching debug image found for frame',
    module: null,
    junk_drawer: { raw_frame: { instruction_addr: '0x00000001010444e4' } },
}

describe('FrameDropDownMenu', () => {
    beforeEach(() => {
        initKeaTests()
    })

    // Radix renders the open menu into a portal that outlives the test without this.
    afterEach(cleanup)

    it('opens with the instruction address when that is all the frame carries', async () => {
        render(<FrameDropDownMenu frame={addressOnlyFrame}>menu</FrameDropDownMenu>)

        await userEvent.click(screen.getByText('menu'))

        expect(await screen.findByText('Copy instruction address')).toBeInTheDocument()
    })

    it('does not open a menu for a frame with nothing to copy', async () => {
        const { container } = render(
            <FrameDropDownMenu frame={{ ...addressOnlyFrame, junk_drawer: undefined }}>menu</FrameDropDownMenu>
        )
        const trigger = container.querySelector('button')!

        expect(trigger).toBeDisabled()

        await userEvent.click(trigger, { pointerEventsCheck: 0 })

        expect(screen.queryByText(/^Copy /)).not.toBeInTheDocument()
    })
})
