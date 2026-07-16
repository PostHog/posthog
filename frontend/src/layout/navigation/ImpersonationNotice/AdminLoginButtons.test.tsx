import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'

import { Region } from '~/types'

import { AdminLoginButtons } from './AdminLoginButtons'

describe('AdminLoginButtons', () => {
    afterEach(cleanup)

    test.each([
        {
            labelStyle: 'default descriptive',
            useRegionLabels: undefined,
            expectedLabels: ['Login as customer@example.com (US)', 'Login as customer@example.com (EU)'],
            unexpectedLabels: ['US region', 'EU region'],
        },
        {
            labelStyle: 'compact region',
            useRegionLabels: true,
            expectedLabels: ['US region', 'EU region'],
            unexpectedLabels: ['Login as customer@example.com (US)', 'Login as customer@example.com (EU)'],
        },
    ])('renders $labelStyle labels', ({ useRegionLabels, expectedLabels, unexpectedLabels }) => {
        render(
            <AdminLoginButtons
                ticketContext={{ ticketId: 'ticket-1', email: 'customer@example.com' }}
                adminLoginUrls={[
                    { region: Region.US, url: 'https://us.posthog.com/admin/posthog/user/' },
                    { region: Region.EU, url: 'https://eu.posthog.com/admin/posthog/user/' },
                ]}
                useRegionLabels={useRegionLabels}
            />
        )

        for (const expectedLabel of expectedLabels) {
            expect(screen.getByText(expectedLabel)).toBeInTheDocument()
        }
        for (const unexpectedLabel of unexpectedLabels) {
            expect(screen.queryByText(unexpectedLabel)).not.toBeInTheDocument()
        }
    })
})
