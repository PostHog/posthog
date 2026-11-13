import { MOCK_DEFAULT_TEAM } from '~/lib/api.mock'

import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { NotesTagsFilter } from './NotesTagsFilter'

describe('NotesTagsFilter', () => {
    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:team_id/tags': () => [
                    200,
                    { results: ['ai-task:unrelated', 'renewal'], next: null, count: 2 },
                ],
                '/api/projects/:team_id/account_notes/tags/': () => [
                    200,
                    { results: [{ name: 'renewal' }], next: null, count: 1 },
                ],
            },
        })
        window.POSTHOG_APP_CONTEXT = { ...window.POSTHOG_APP_CONTEXT, current_team: MOCK_DEFAULT_TEAM } as any
        initKeaTests()
    })

    afterEach(() => {
        cleanup()
    })

    it('offers only the tags already on account notes', async () => {
        render(<NotesTagsFilter value={[]} onChange={jest.fn()} />)

        fireEvent.click(screen.getByText('All tags'))

        expect(await screen.findByText('renewal')).toBeInTheDocument()
        expect(screen.queryByText('ai-task:unrelated')).not.toBeInTheDocument()
    })
})
