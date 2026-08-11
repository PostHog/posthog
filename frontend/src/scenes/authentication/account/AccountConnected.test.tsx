import { render } from '@testing-library/react'
import { router } from 'kea-router'

import { initKeaTests } from '~/test/init'

import { AccountConnected, resolveConnectStatus } from './AccountConnected'

describe('AccountConnected', () => {
    beforeEach(() => {
        initKeaTests()
    })

    it('a pending install from Slack shows the waiting state and an exit button, not a failure', () => {
        // project_id is pushed as a number, mirroring how kea-router decodes `project_id=2` from the
        // real backend redirect — the exit button must still render, not silently no-op.
        router.actions.push('/account-connected/github-integration', {
            provider: 'github',
            project_id: 2,
            connect_from: 'slack',
            github_install_pending: '1',
        })
        const { container } = render(<AccountConnected kind="github-integration" />)
        const text = container.textContent || ''
        expect(text).toContain('GitHub installation waiting for approval')
        // The org-owner explanation now reaches the page on the Slack flow (previously desktop-only).
        expect(text).toContain('organization owner')
        expect(text).toContain('Continue to PostHog')
        expect(text).not.toContain('connection failed')
    })

    it('a real error still wins over the pending marker', () => {
        // Guards against folding pending back into the error path, or letting it mask a genuine failure.
        expect(resolveConnectStatus({ provider: 'github', github_install_pending: '1' })).toBe('pending')
        expect(
            resolveConnectStatus({ provider: 'github', error: 'exchange_failed', github_install_pending: '1' })
        ).toBe('error')
        expect(resolveConnectStatus({ provider: 'github' })).toBe('success')
    })
})
