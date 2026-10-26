import { LemonButton } from '@posthog/lemon-ui'

import { MemberSelect } from 'lib/components/MemberSelect'

export function MetricOwnerSelect({
    owner,
    loading,
    disabledReason,
    onChange,
}: {
    owner: string | null | undefined
    loading: boolean
    disabledReason?: string
    onChange: (owner: string | null) => void
}): JSX.Element {
    return (
        <MemberSelect value={null} defaultLabel="Unassigned" onChange={(user) => onChange(user?.email ?? null)}>
            {() => (
                <LemonButton
                    type="tertiary"
                    size="small"
                    className="-ml-2 -my-1.5"
                    loading={loading}
                    disabledReason={disabledReason}
                    data-attr="data-catalog-metric-owner-select"
                >
                    {owner || 'Unassigned'}
                </LemonButton>
            )}
        </MemberSelect>
    )
}
