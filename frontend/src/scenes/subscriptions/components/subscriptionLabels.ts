import type { SubscriptionApi } from '@posthog/products-subscriptions/frontend/generated/api.schemas'
import { TargetTypeEnumApi } from '@posthog/products-subscriptions/frontend/generated/api.schemas'

export const TARGET_TYPE_LABEL: Record<SubscriptionApi['target_type'], string> = {
    [TargetTypeEnumApi.Email]: 'Email',
    [TargetTypeEnumApi.Slack]: 'Slack',
}
