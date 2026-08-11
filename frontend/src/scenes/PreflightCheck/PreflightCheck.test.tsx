import '@testing-library/jest-dom'

import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Provider } from 'kea'
import { router } from 'kea-router'

import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { PreflightCheck } from './PreflightCheck'

const preflightSuccessResponse = {
    django: true,
    redis: true,
    plugins: true,
    celery: true,
    clickhouse: true,
    kafka: true,
    db: true,
    initiated: true,
    cloud: false,
    demo: false,
    realm: 'hosted-clickhouse',
    region: null,
    available_social_auth_providers: { github: false, gitlab: false, 'google-oauth2': false },
    can_create_org: true,
    email_service_available: true,
    slack_service: { available: false, client_id: null },
    object_storage: true,
}

describe('PreflightCheck', () => {
    beforeEach(() => {
        initKeaTests()
    })

    afterEach(() => {
        cleanup()
    })

    function useSetupMocks(preflightOverrides: Record<string, unknown> = {}): void {
        useMocks({
            get: {
                '/_preflight': { ...preflightSuccessResponse, ...preflightOverrides },
            },
        })
    }

    function renderPreflight(): void {
        render(
            <Provider>
                <PreflightCheck />
            </Provider>
        )
    }

    function statusTexts(): string[] {
        return screen.getAllByTestId('status-text').map((el) => el.textContent ?? '')
    }

    function countStatus(status: string): number {
        return statusTexts().filter((text) => text === status).length
    }

    // jsdom serves over http, so the TLS check is the one expected warning in live mode
    // (and the one "optional" in experimentation mode).
    it.each([
        {
            description: 'all services healthy allows continuing',
            overrides: {},
            expectedValidated: 9,
            expectedWarning: 1,
            expectedError: 0,
            canContinue: true,
        },
        {
            description: 'a required service being down blocks continuing',
            overrides: { celery: false },
            expectedValidated: 8,
            expectedWarning: 1,
            expectedError: 1,
            canContinue: false,
        },
    ])(
        'live mode: $description',
        async ({ overrides, expectedValidated, expectedWarning, expectedError, canContinue }) => {
            useSetupMocks(overrides)
            renderPreflight()

            await userEvent.click(await screen.findByTestId('preflight-live'))

            await waitFor(() => {
                expect(countStatus('Validated')).toBe(expectedValidated)
            })
            expect(countStatus('Warning')).toBe(expectedWarning)
            expect(countStatus('Error')).toBe(expectedError)
            expect(screen.getByText('Set up before ingesting real user data')).toBeInTheDocument()

            if (canContinue) {
                expect(screen.getByTestId('preflight-complete')).toBeInTheDocument()
                expect(
                    screen.queryByText('All required checks must pass before you can continue')
                ).not.toBeInTheDocument()
            } else {
                expect(screen.queryByTestId('preflight-complete')).not.toBeInTheDocument()
                expect(screen.getByText('All required checks must pass before you can continue')).toBeInTheDocument()
            }
        }
    )

    it('experimentation mode: TLS is optional and completing routes to signup', async () => {
        useSetupMocks()
        renderPreflight()

        await userEvent.click(await screen.findByTestId('preflight-experimentation'))

        await waitFor(() => {
            expect(countStatus('Optional')).toBe(1)
        })
        expect(screen.getByTestId('preflight-refresh')).toBeInTheDocument()
        expect(screen.getByText('Not required for experimentation mode')).toBeInTheDocument()

        await userEvent.click(screen.getByTestId('preflight-complete'))

        await waitFor(() => {
            expect(router.values.location.pathname).toBe(urls.signup())
        })
    })
})
