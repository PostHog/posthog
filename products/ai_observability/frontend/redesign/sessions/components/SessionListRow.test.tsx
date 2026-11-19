import { cleanup, render, screen } from '@testing-library/react'

import { initKeaTests } from '~/test/init'

import { makeTracePersonItem, makeTracePreview, ready } from '../../traces/testFixtures'
import { makeSessionListItem } from '../testFixtures'
import { SessionListRow, type SessionListRowProps } from './SessionListRow'

const ITEM = makeSessionListItem()

function renderRow(overrides: Partial<SessionListRowProps> = {}): void {
    render(
        <SessionListRow
            item={ITEM}
            title={ready(makeTracePreview(ITEM.firstTraceId))}
            person={ready(makeTracePersonItem(ITEM.firstTraceId).person)}
            isOpen={false}
            {...overrides}
        />
    )
}

describe('SessionListRow', () => {
    beforeEach(() => initKeaTests())
    afterEach(cleanup)

    it('shows the first prompt as the title with the session facts', () => {
        renderRow()

        expect(screen.getByText('Why was I charged twice this month?')).not.toBeNull()
        expect(screen.getByText('6 turns · 27m · $0.0126')).not.toBeNull()
    })

    it('names a session with no input untitled', () => {
        renderRow({ title: ready(makeTracePreview('t', { input: null })) })

        expect(screen.getByText('Untitled session')).not.toBeNull()
    })

    it('says 1 turn in the singular', () => {
        renderRow({ item: makeSessionListItem({ turnCount: 1 }) })

        expect(screen.getByText(/^1 turn · /)).not.toBeNull()
    })

    it('shows the failure mark for a failed title read', () => {
        renderRow({ title: { status: 'error' } })

        expect(screen.getAllByRole('img', { name: /Couldn't load this/ }).length).toBeGreaterThan(0)
    })
})
