import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'

import { ChannelsTag } from './ChannelsTag'

describe('ChannelsTag', () => {
    afterEach(cleanup)

    it('shows the connected address an email ticket came in on', () => {
        render(<ChannelsTag channel="email" emailTo="support@example.com" />)
        expect(screen.getByText('· support@example.com')).toBeInTheDocument()
    })

    it('omits the address when the ticket has no receiving address', () => {
        render(<ChannelsTag channel="email" />)
        expect(screen.queryByText(/·/)).not.toBeInTheDocument()
    })
})
