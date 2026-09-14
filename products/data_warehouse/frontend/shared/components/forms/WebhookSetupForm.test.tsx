import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'

import { SourceConfig } from '~/queries/schema/schema-general'

import { WebhookSetupForm } from './WebhookSetupForm'

const FAILED_RESULT = { success: false, webhook_url: 'https://example.com/hook', error: 'Store rejected the request' }

function renderFallback(
    sourceConfig: Partial<SourceConfig>,
    onCreateWebhook: () => void = jest.fn(),
    autoCreationBlockedReason?: string
): void {
    render(
        <WebhookSetupForm
            sourceName="WooCommerce"
            sourceConfig={{ name: 'WooCommerce', fields: [], ...sourceConfig } as unknown as SourceConfig}
            webhookResult={FAILED_RESULT}
            webhookCreating={false}
            autoCreationBlockedReason={autoCreationBlockedReason}
            onCreateWebhook={onCreateWebhook}
        />
    )
}

describe('WebhookSetupForm', () => {
    afterEach(cleanup)

    it('offers a retry after automatic creation fails', () => {
        const onCreateWebhook = jest.fn()
        renderFallback({}, onCreateWebhook)

        fireEvent.click(screen.getByText('Try again'))

        expect(onCreateWebhook).toHaveBeenCalledTimes(1)
    })

    it.each([
        ['the source only supports manual setup', { webhookManualOnly: true }, undefined],
        ['the connection cannot register webhooks', {}, 'This connection cannot manage webhooks.'],
    ])('offers no retry when %s', (_name, sourceConfig, autoCreationBlockedReason) => {
        renderFallback(sourceConfig, jest.fn(), autoCreationBlockedReason)

        expect(screen.queryByText('Try again')).not.toBeInTheDocument()
    })
})
