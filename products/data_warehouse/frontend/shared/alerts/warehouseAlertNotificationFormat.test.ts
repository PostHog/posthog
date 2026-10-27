import { WarehouseAlertDestinationTypeEnumApi } from 'products/warehouse_sources/frontend/generated/api.schemas'

import { describeNotification } from './warehouseAlertNotificationFormat'

describe('describeNotification', () => {
    it.each([
        ['a pending webhook by its host', 'https://hooks.example.com/services/T000/B000/secret', 'hooks.example.com'],
        ['a saved webhook, already reduced to its host', 'hooks.example.com', 'hooks.example.com'],
    ])('shows %s', (_, webhookUrl, expected) => {
        expect(
            describeNotification({ type: WarehouseAlertDestinationTypeEnumApi.Webhook, webhook_url: webhookUrl })
        ).toEqual({ title: 'Webhook', detail: expected })
    })
})
