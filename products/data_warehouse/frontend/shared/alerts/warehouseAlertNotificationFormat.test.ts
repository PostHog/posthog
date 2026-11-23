import { WarehouseAlertDestinationTypeEnumApi } from 'products/warehouse_sources/frontend/generated/api.schemas'

import { describeNotification } from './warehouseAlertNotificationFormat'

describe('describeNotification', () => {
    it.each([
        ['a pending webhook by its host', 'https://hooks.example.com/services/T000/B000/secret', 'hooks.example.com'],
        ['a saved webhook, already reduced to its scheme and host', 'https://hooks.example.com', 'hooks.example.com'],
        ['no part of a webhook URL without a scheme', 'hooks.example.com/services/T000/B000/secret', undefined],
    ])('shows %s', (_, webhookUrl, expected) => {
        expect(
            describeNotification({ type: WarehouseAlertDestinationTypeEnumApi.Webhook, webhook_url: webhookUrl })
        ).toEqual({ title: 'Webhook', detail: expected })
    })

    it.each([
        ['the names of the members it emails', [1, 2], 'Ada Lovelace, grace@example.com'],
        ['a count for members without a known name', [1, 7, 8], 'Ada Lovelace, 2 more'],
        ['only a count when no member has a known name', [7], '1 project member'],
    ])('shows %s', (_, userIds, expected) => {
        expect(
            describeNotification(
                { type: WarehouseAlertDestinationTypeEnumApi.Email, email_user_ids: userIds },
                { 1: 'Ada Lovelace', 2: 'grace@example.com' }
            )
        ).toEqual({ title: 'Email', detail: expected })
    })
})
