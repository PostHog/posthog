import type { AccountViewApi } from '../../generated/api.schemas'
import { createAccountViewContent } from '../../scenes/CustomerAnalyticsAccountScene/accountViewDocument'
import { getAccountProductActivityUrl } from './accountProductActivityUrl'

const view = (id: string, source: unknown): AccountViewApi =>
    ({
        id,
        content: createAccountViewContent([{ kind: 'dot_matrix', nodeId: id, span: 12, config: { source } }]),
    }) as AccountViewApi

describe('getAccountProductActivityUrl', () => {
    it('opens a saved product view, skipping other sources and blank drafts', () => {
        expect(
            getAccountProductActivityUrl('account', [
                view('blank', null),
                view('usage', { kind: 'usage_metrics' }),
                view('product', { kind: 'product_usage' }),
            ])
        ).toBe('/customer_analytics/accounts/account/view%3Aproduct')
    })
    it('requests deliberate setup when there is no configured product view', () => {
        expect(getAccountProductActivityUrl('account', [view('blank', null)])).toBe(
            '/customer_analytics/accounts/account?setup=product-activity'
        )
    })
})
