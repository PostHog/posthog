import type { SubscriptionDeliveryApi } from '~/generated/core/api.schemas'
import { SubscriptionDeliveryStatusEnumApi } from '~/generated/core/api.schemas'

import { rowHasExpandedContent } from './SubscriptionDeliveryHistory'

function makeDelivery(overrides: Partial<SubscriptionDeliveryApi>): SubscriptionDeliveryApi {
    return {
        id: 'd',
        subscription: 1,
        temporal_workflow_id: 'wf',
        idempotency_key: 'k',
        trigger_type: 'scheduled',
        scheduled_at: null,
        target_type: 'email',
        target_value: 'x@y',
        exported_asset_ids: [],
        content_snapshot: {},
        recipient_results: [],
        status: SubscriptionDeliveryStatusEnumApi.Completed,
        error: null,
        change_summary: null,
        created_at: '2026-04-01T00:00:00Z',
        last_updated_at: '2026-04-01T00:00:00Z',
        finished_at: null,
        ...overrides,
    }
}

describe('rowHasExpandedContent', () => {
    test.each<[string, Partial<SubscriptionDeliveryApi>, boolean]>([
        ['neither summary nor assets', {}, false],
        ['summary only', { change_summary: { summary: 'all good' } }, true],
        ['assets only', { exported_asset_ids: [101] }, true],
        ['both', { change_summary: { summary: 'all good' }, exported_asset_ids: [101, 102] }, true],
        // Empty summary object with no assets should NOT claim expandability — the expanded row
        // would render nothing. Prevents a confusing "click-caret-to-see-empty" UX.
        ['empty summary object, no assets', { change_summary: {} }, false],
        ['empty summary string, no assets', { change_summary: { summary: '' } }, false],
        ['empty summary object with assets', { change_summary: {}, exported_asset_ids: [101] }, true],
    ])('%s → %s', (_label, overrides, expected) => {
        expect(rowHasExpandedContent(makeDelivery(overrides))).toBe(expected)
    })
})
