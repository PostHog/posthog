import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { Provider } from 'kea'

import { OrganizationMembershipLevel } from 'lib/constants'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { OtherIntegrations } from './OtherIntegrations'

describe('OtherIntegrations', () => {
    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:team_id/integrations': () => [200, { results: [] }],
            },
            post: {
                '/api/environments/:team_id/integrations': () => [
                    200,
                    {
                        id: 42,
                        kind: 'aws-s3',
                        display_name: 'Test connection',
                        icon_url: '',
                        config: {},
                        created_by: null,
                        created_at: '2026-01-01T00:00:00Z',
                    },
                ],
            },
        })
        initKeaTests()
    })

    afterEach(() => {
        cleanup()
    })

    it('creates an AWS S3 connection without leaving settings', async () => {
        // An S3 batch export needs an aws-s3 integration, and the destination form sends people
        // here to make one. Settings used to render a read-only list, so the only way to create
        // one was the picker the user had just left.
        render(
            <Provider>
                <OtherIntegrations />
            </Provider>
        )

        fireEvent.click(await screen.findByText('New connection'))
        fireEvent.click(await screen.findByText('AWS S3'))

        fireEvent.change(await screen.findByPlaceholderText('e.g. Production data lake'), {
            target: { value: 'Test connection' },
        })
        fireEvent.change(screen.getByPlaceholderText(/arn:aws:iam/), {
            target: { value: 'arn:aws:iam::123456789012:role/posthog' },
        })
        fireEvent.click(screen.getByText('Save'))

        await waitFor(() => {
            expect(screen.queryByText('IAM role ARN')).not.toBeInTheDocument()
        })
    })

    it('disables creating for a member who cannot manage integrations', async () => {
        initKeaTests(true, {
            ...MOCK_DEFAULT_TEAM,
            effective_membership_level: OrganizationMembershipLevel.Member,
        })

        render(
            <Provider>
                <OtherIntegrations />
            </Provider>
        )

        fireEvent.click(await screen.findByText('New connection'))
        const item = await screen.findByText('AWS S3')
        expect(item.closest('[aria-disabled]')).toHaveAttribute('aria-disabled', 'true')
    })
})
