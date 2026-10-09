import { LemonTag, Tooltip } from '@posthog/lemon-ui'

import type { CloudAgentRunStatusEnumApi, CloudAgentRunStatusReasonEnumApi } from '../generated/api.schemas'
import { getRunStatusDisplay } from '../utils/runStatus'

export function RunStatusTag({
    status,
    reason,
    detail,
}: {
    status: CloudAgentRunStatusEnumApi
    reason: CloudAgentRunStatusReasonEnumApi | null
    detail?: string | null
}): JSX.Element {
    const { label, type, tooltip } = getRunStatusDisplay(status, reason, detail)
    const tag = <LemonTag type={type}>{label}</LemonTag>
    return tooltip ? <Tooltip title={tooltip}>{tag}</Tooltip> : tag
}
