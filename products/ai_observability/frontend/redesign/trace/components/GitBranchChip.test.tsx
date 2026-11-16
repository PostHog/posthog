import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { urls } from 'scenes/urls'

import { initKeaTests } from '~/test/init'

import { GitBranchChip } from './GitBranchChip'

const PULL_REQUEST = { repoOwner: 'acme', repoName: 'app', number: 42, title: 'Answer billing questions' }

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
        expect(screen.getByText('feat/rag').closest('a')?.getAttribute('href')).toContain(
            urls.engineeringAnalyticsPullRequest('acme', 'app', 42)
        )
    })
})
