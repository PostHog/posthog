import { render } from '@testing-library/react'

import { BlastRadiusErrorMessage } from './BlastRadiusErrorMessage'

describe('BlastRadiusErrorMessage', () => {
    it('linkifies a trusted PostHog docs URL in the backend message', () => {
        const { container } = render(
            <BlastRadiusErrorMessage
                error={{
                    status: 513,
                    code: 'clickhouse_memory_limit_exceeded',
                    detail: 'Ran out of memory. See https://posthog.com/docs/feature-flags for more.',
                }}
                pluralName="users"
            />
        )
        const link = container.querySelector('a')
        expect(link).not.toBeNull()
        expect(link?.getAttribute('href')).toBe('https://posthog.com/docs/feature-flags')
    })

    // The detail can echo user-controlled filter text, so a non-PostHog URL must not become a link.
    it('does not linkify an untrusted URL', () => {
        const { container } = render(
            <BlastRadiusErrorMessage
                error={{ status: 400, detail: 'Bad filter: see https://evil.example.com/phish' }}
                pluralName="users"
            />
        )
        expect(container.querySelector('a')).toBeNull()
        expect(container.textContent).toContain('https://evil.example.com/phish')
    })

    it('falls back to a generic line without a detail', () => {
        const { container } = render(<BlastRadiusErrorMessage error={{ status: 500 }} pluralName="organizations" />)
        expect(container.textContent).toBe("Couldn't estimate how many organizations match.")
    })
})
