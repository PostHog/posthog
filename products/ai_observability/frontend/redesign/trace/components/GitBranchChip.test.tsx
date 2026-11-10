import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { initKeaTests } from '~/test/init'

import { GitBranchChip } from './GitBranchChip'

const PULL_REQUEST = { number: 42, title: 'Answer billing questions', href: '/engineering-analytics/pull-requests/42' }

describe('GitBranchChip', () => {
    beforeEach(() => {
        initKeaTests()
    })

    afterEach(() => {
        cleanup()
    })

    it('opens its tooltip on hover once the pull request arrives after the chip rendered', async () => {
        const { rerender } = render(<GitBranchChip branch="feat/rag" repo="acme/app" pullRequest={null} />)
        rerender(<GitBranchChip branch="feat/rag" repo="acme/app" pullRequest={PULL_REQUEST} />)

        await userEvent.hover(screen.getByText('feat/rag'))

        expect(
            await screen.findByText(
                'Git branch feat/rag in acme/app. Opens pull request #42 in engineering analytics: Answer billing questions'
            )
        ).toBeTruthy()
    })
})
