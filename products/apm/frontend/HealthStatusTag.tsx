import { LemonTag } from '@posthog/lemon-ui'

import type { HealthStatusEnumApi } from './generated/api.schemas'
import { STATUS_LABEL, STATUS_TAG } from './healthDisplay'

export function HealthStatusTag({ status }: { status: HealthStatusEnumApi }): JSX.Element {
    return <LemonTag type={STATUS_TAG[status]}>{STATUS_LABEL[status]}</LemonTag>
}
