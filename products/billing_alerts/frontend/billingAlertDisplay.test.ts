import { stateLabel } from './billingAlertDisplay'
import type { BillingAlertConfigurationApi } from './generated/api.schemas'

describe('billing alert display', () => {
    it('uses the notification lifecycle name for broken alerts', () => {
        expect(stateLabel({ state: 'broken', enabled: false } as BillingAlertConfigurationApi)).toBe('Auto-disabled')
    })
})
