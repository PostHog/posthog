import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'

import { SandboxPullRequestCard } from './SandboxPullRequestCard'
import { SandboxRunContext } from './SandboxRunContext'

const PR_URL = 'https://github.com/PostHog/posthog/pull/123'

describe('sandbox git artifacts', () => {
    afterEach(() => {
        cleanup()
    })

    it('SandboxRunContext self-hides with no branch', () => {
        const { container } = render(<SandboxRunContext />)
        expect(container).toBeEmptyDOMElement()
    })

    it('SandboxRunContext renders the working and base branch', () => {
        render(<SandboxRunContext branch="feat/x" baseBranch="master" repo="PostHog/posthog" />)
        expect(screen.getByText('feat/x')).toBeInTheDocument()
        expect(screen.getByText('master')).toBeInTheDocument()
        expect(screen.getByText('PostHog/posthog')).toBeInTheDocument()
    })

    it('SandboxPullRequestCard self-hides with no pr url', () => {
        const { container } = render(<SandboxPullRequestCard branch="feat/x" />)
        expect(container).toBeEmptyDOMElement()
    })

    it('SandboxPullRequestCard renders the success card and a link to the PR', () => {
        render(<SandboxPullRequestCard prUrl={PR_URL} branch="feat/x" />)
        expect(screen.getByText('Pull request opened')).toBeInTheDocument()
        expect(screen.getByText('feat/x')).toBeInTheDocument()
        expect(screen.getByRole('link', { name: /Open on GitHub/ })).toHaveAttribute('href', PR_URL)
    })
})
