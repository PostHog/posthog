import type { SubscriptionApi } from '~/generated/core/api.schemas'
import { TargetTypeEnumApi } from '~/generated/core/api.schemas'

export const TARGET_TYPE_LABEL: Record<SubscriptionApi['target_type'], string> = {
    [TargetTypeEnumApi.Email]: 'Email',
    [TargetTypeEnumApi.Slack]: 'Slack',
    [TargetTypeEnumApi.Webhook]: 'Webhook',
}
