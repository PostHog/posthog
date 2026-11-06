import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'

import type { SourceConfigResponseApi } from 'products/warehouse_sources/frontend/generated/api.schemas'

import { WebhookSetupForm } from './WebhookSetupForm'

const FAILED_RESULT = { success: false, webhook_url: 'https://example.com/hook', error: 'Store rejected the request' }

function renderFallback(
    sourceConfig: Partial<SourceConfigResponseApi>,
    onCreateWebhook: () => void = jest.fn(),
    autoCreationBlockedReason?: string,
    webhookResult: typeof FAILED_RESULT = FAILED_RESULT
): void {
    render(
        <WebhookSetupForm
            sourceName="WooCommerce"
            sourceConfig={{ name: 'WooCommerce', fields: [], ...sourceConfig } as unknown as SourceConfigResponseApi}
            webhookResult={webhookResult}
            webhookCreating={false}
            autoCreationBlockedReason={autoCreationBlockedReason}
            onCreateWebhook={onCreateWebhook}
        />
    )
}

describe('WebhookSetupForm', () => {
    afterEach(cleanup)

    it.each([
        ['automatic creation fails', {}, FAILED_RESULT],
        [
            'a manual-only source gets no webhook URL',
            { webhookManualOnly: true },
            { ...FAILED_RESULT, webhook_url: '' },
        ],
    ])('offers a retry when %s', (_name, sourceConfig, webhookResult) => {
        const onCreateWebhook = jest.fn()
        renderFallback(sourceConfig, onCreateWebhook, undefined, webhookResult)

        expect(screen.getByText(webhookResult.error)).toBeInTheDocument()
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
