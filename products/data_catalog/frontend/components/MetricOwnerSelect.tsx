import { LemonButton } from '@posthog/lemon-ui'

import { MemberSelect } from 'lib/components/MemberSelect'

export function MetricOwnerSelect({
    owner,
    loading,
    disabledReason,
    onChange,
    truncate,
}: {
    owner: string | null | undefined
    loading: boolean
    disabledReason?: string
    onChange: (owner: string | null) => void
    /** Cut a long owner email with an ellipsis, with the full email on hover. */
    truncate?: boolean
}): JSX.Element {
    return (
        <MemberSelect value={null} defaultLabel="Unassigned" onChange={(user) => onChange(user?.email ?? null)}>
            {() => (
                <LemonButton
                    type="tertiary"
                    size="small"
                    className={truncate ? '-ml-2 -my-1.5 max-w-40' : '-ml-2 -my-1.5'}
                    truncate={truncate}
                    tooltip={truncate && owner ? owner : undefined}
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
