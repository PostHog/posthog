import '@testing-library/jest-dom'

import { render, screen } from '@testing-library/react'

import type { TicketBriefAffectedItemApi, TicketBriefApi } from '../../generated/api.schemas'
import { TicketBriefPanel } from './TicketBriefPanel'

const BRIEF: TicketBriefApi = {
    ask: 'Explain why the export is empty.',
    area: 'Batch exports',
    questions: ['Why is it empty?'],
}

describe('TicketBriefPanel', () => {
    it('renders a backticked identifier as code', () => {
        render(<TicketBriefPanel brief={{ ...BRIEF, ask: 'Raise the cap on `checkout-redesign`.' }} />)

        expect(screen.getByText('checkout-redesign').tagName).toEqual('CODE')
    })

    it.each([
        ['no ask', { area: 'Billing', questions: ['Why?'] }],
        ['no questions', { ask: 'Raise the limit.', area: 'Billing' }],
        ['only an area', { area: 'Billing' }],
    ])('renders without throwing when a stored brief has %s', (_name, brief) => {
        // A brief is written by an agent, so one already stored can be missing a field the
        // schema calls required. Reading it as present took the whole ticket scene down once.
        expect(() => render(<TicketBriefPanel brief={brief as TicketBriefApi} />)).not.toThrow()
    })

    it('leaves out an affected item that has no url', () => {
        render(
            <TicketBriefPanel
                brief={{
                    ...BRIEF,
                    affected_items: [
                        { kind: 'insight', label: 'Conversion', url: 'https://example.com/insight' },
                        { kind: 'insight', label: 'Broken' } as TicketBriefAffectedItemApi,
                    ],
                }}
            />
        )

        expect(screen.getByText('Insight: Conversion')).toBeInTheDocument()
        expect(screen.queryByText('Insight: Broken')).not.toBeInTheDocument()
    })
})
