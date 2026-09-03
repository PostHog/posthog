import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { Provider } from 'kea'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { IntegrationType } from '~/types'

import { IntegrationChoice } from './IntegrationChoice'

const GITHUB_INTEGRATION: IntegrationType = {
    id: 1,
    kind: 'github',
    display_name: 'sortafreel',
    icon_url: '',
    config: {},
    created_by: null,
    created_at: '2026-01-01T00:00:00Z',
}

describe('IntegrationChoice', () => {
    beforeEach(() => {
        useMocks({
            get: {
                '/api/environments/:team_id/integrations': () => [200, { results: [GITHUB_INTEGRATION] }],
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

    it('matches a string-typed id to its numeric connection (no false "no longer available")', async () => {
        // MCP-created data-warehouse sources persist the integration id as the string "1", while
        // the integration's real id is the number 1. The connection exists, so the warning must
        // NOT show — the connected integration resolves and the menu offers "Change".
        render(
            <Provider>
                <IntegrationChoice integration="github" value={'1' as unknown as number} onChange={jest.fn()} />
            </Provider>
        )

        await waitFor(() => {
            expect(screen.getByText('Change')).toBeInTheDocument()
        })
        expect(screen.queryByText(/no longer available/)).not.toBeInTheDocument()
    })

    it('auto-selects the first integration only once, even when the written value lags re-renders', async () => {
        // The consumer's write can take a full state round-trip before it flows back into the
        // `value` prop (e.g. the workflow editor rebuilds its graph first). Re-firing the
        // auto-select on every render in that window dispatches an update per render, which can
        // amplify into an infinite update loop (React #185).
        const onChange = jest.fn()
        const view = render(
            <Provider>
                <IntegrationChoice integration="github" onChange={onChange} />
            </Provider>
        )

        await waitFor(() => {
            expect(onChange).toHaveBeenCalledWith(1)
        })

        // Value prop still unset, as during the consumer's write round-trip. rerender flushes
        // effects synchronously, so a repeat dispatch would have happened by the assertion.
        view.rerender(
            <Provider>
                <IntegrationChoice integration="github" onChange={onChange} />
            </Provider>
        )
        expect(onChange).toHaveBeenCalledTimes(1)
    })

    it('routes a new connection to the picker that opened the modal, not a same-kind sibling', async () => {
        // A Redshift COPY export renders two aws-s3 pickers that share one unkeyed setup-modal
        // logic. Completing the modal opened from the first picker must call the first picker's
        // onChange — not the last-rendered sibling's, which would drop the new id into the wrong
        // field and fail the backend kind check on save.
        const onChangeFirst = jest.fn()
        const onChangeSecond = jest.fn()
        render(
            <Provider>
                <div data-attr="picker-first">
                    <IntegrationChoice integration="aws-s3" onChange={onChangeFirst} />
                </div>
                <div data-attr="picker-second">
                    <IntegrationChoice integration="aws-s3" onChange={onChangeSecond} />
                </div>
            </Provider>
        )

        const firstTrigger = await within(screen.getByTestId('picker-first')).findByText('Choose AWS S3 connection')
        fireEvent.click(firstTrigger)
        fireEvent.click(await screen.findByText('Configure new AWS S3 connection'))

        // Fill the minimal valid form (default 'Assume IAM role' mode) and save.
        fireEvent.change(await screen.findByPlaceholderText('e.g. Production data lake'), {
            target: { value: 'Test connection' },
        })
        fireEvent.change(screen.getByPlaceholderText(/arn:aws:iam/), {
            target: { value: 'arn:aws:iam::123456789012:role/posthog' },
        })
        fireEvent.click(screen.getByText('Save'))

        await waitFor(() => {
            expect(onChangeFirst).toHaveBeenCalledWith(42)
        })
        expect(onChangeSecond).not.toHaveBeenCalled()
    })

    it('still warns when the stored id matches no integration', async () => {
        // Regression guard: a genuinely dangling reference must keep surfacing the banner.
        render(
            <Provider>
                <IntegrationChoice integration="github" value={999} onChange={jest.fn()} />
            </Provider>
        )

        await waitFor(() => {
            expect(screen.getByText(/no longer available/)).toBeInTheDocument()
        })
    })
})
