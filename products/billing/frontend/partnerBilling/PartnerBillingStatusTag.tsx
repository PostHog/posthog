import { LemonTag, LemonTagType } from '@posthog/lemon-ui'

import { capitalizeFirstLetter } from 'lib/utils/strings'

const TAG_TYPE_BY_STATUS: Record<string, LemonTagType> = {
    paid: 'success',
    failed: 'danger',
    uncollectible: 'danger',
    void: 'muted',
}

export function PartnerBillingStatusTag({ status }: { status: string }): JSX.Element {
    return (
        <LemonTag type={TAG_TYPE_BY_STATUS[status] ?? 'default'}>
            {capitalizeFirstLetter(status.replace(/_/g, ' '))}
        </LemonTag>
    )
}
