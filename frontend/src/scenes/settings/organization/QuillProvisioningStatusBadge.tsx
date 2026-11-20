import { Badge } from '@posthog/quill'

import { quillBadgeVariant } from 'lib/lemon-ui/LemonTag/quillBadgeVariant'

import { PartnerProvisioningStatusEnumApi } from '~/generated/core/api.schemas'

import { PROVISIONING_STATUS_LABELS, PROVISIONING_STATUS_TAG_TYPES } from './oauthAppProvisioningStatus'

export function QuillProvisioningStatusBadge({ status }: { status: PartnerProvisioningStatusEnumApi }): JSX.Element {
    return (
        <Badge variant={quillBadgeVariant(PROVISIONING_STATUS_TAG_TYPES[status])}>
            {PROVISIONING_STATUS_LABELS[status]}
        </Badge>
    )
}
