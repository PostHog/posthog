import { cleanup, render, screen } from '@testing-library/react'

import { Region } from '~/types'

import { AdminLoginButtons } from './AdminLoginButtons'

const multiRegionAdminLoginUrls = [
    { region: Region.US, url: 'https://us.posthog.com/admin/posthog/user/' },
    { region: Region.EU, url: 'https://eu.posthog.com/admin/posthog/user/' },
]

describe('AdminLoginButtons', () => {
    afterEach(cleanup)

    test.each([
        {
            labelStyle: 'default descriptive',
            adminLoginUrls: multiRegionAdminLoginUrls,
            useRegionLabels: undefined,
            expectedLabels: ['Login as customer@example.com (US)', 'Login as customer@example.com (EU)'],
        },
        {
            labelStyle: 'single-region default descriptive',
            adminLoginUrls: [{ region: Region.US, url: 'https://us.posthog.com/admin/posthog/user/' }],
            useRegionLabels: undefined,
            expectedLabels: ['Login as customer@example.com'],
        },
        {
            labelStyle: 'compact region',
            adminLoginUrls: multiRegionAdminLoginUrls,
            useRegionLabels: true,
            expectedLabels: ['US region', 'EU region'],
        },
    ])('renders $labelStyle labels', ({ adminLoginUrls, useRegionLabels, expectedLabels }) => {
        render(
            <AdminLoginButtons
                ticketContext={{ ticketId: 'ticket-1', email: 'customer@example.com' }}
                adminLoginUrls={adminLoginUrls}
                useRegionLabels={useRegionLabels}
            />
        )

        expect(screen.getAllByRole('button').map((button) => button.textContent)).toEqual(expectedLabels)
    })
})
