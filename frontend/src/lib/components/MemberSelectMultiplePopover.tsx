import { useActions, useValues } from 'kea'

import { IconX } from '@posthog/icons'
import { LemonDropdown } from '@posthog/lemon-ui'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { membersLogic } from 'scenes/organization/membersLogic'

import { MemberSelectMultipleOptions } from './MemberSelectMultipleOptions'

export type MemberSelectMultiplePopoverProps = {
    /** Currently selected member user ids. */
    value: number[]
    onChange: (value: number[]) => void
    /** Trigger button label, also used in the "<label> you" / "<label> (N)" summaries. */
    label?: string
    /** When true, the trigger appears borderless (alt status) while nothing is selected. */
    borderless?: boolean
}

/**
 * Multi-select of organization members rendered as a labeled dropdown with a searchable,
 * checkbox member list. Shared by the dashboards and insights "Created by" filters.
 *
 * For a single-select member picker use `MemberSelect`; for a chip-style multi-select input
 * use `MemberSelectMultiple`.
 */
export function MemberSelectMultiplePopover({
    value,
    onChange,
    label = 'Created by',
    borderless = false,
}: MemberSelectMultiplePopoverProps): JSX.Element {
    const { me } = useValues(membersLogic)
    const { ensureAllMembersLoaded, setSearch } = useActions(membersLogic)

    const hasSelection = value.length > 0
    const isFilteredToCurrentUser = hasSelection && value.length === 1 && value[0] === me?.user.id

    return (
        <LemonDropdown
            closeOnClickInside={false}
            matchWidth={false}
            placement="bottom-end"
            actionable
            onVisibilityChange={(visible) => {
                if (visible) {
                    ensureAllMembersLoaded()
                    setSearch('')
                }
            }}
            overlay={<MemberSelectMultipleOptions value={value} onChange={onChange} />}
        >
            <LemonButton
                size="small"
                type="secondary"
                status={borderless && !hasSelection ? 'alt' : 'default'}
                active={hasSelection}
                sideAction={
                    hasSelection
                        ? {
                              icon: <IconX />,
                              tooltip: 'Clear selection',
                              divider: false,
                              'data-attr': 'member-filter-clear-x',
                              onClick: (e) => {
                                  e.stopPropagation()
                                  onChange([])
                              },
                          }
                        : null
                }
            >
                {isFilteredToCurrentUser ? `${label} you` : hasSelection ? `${label} (${value.length})` : label}
            </LemonButton>
        </LemonDropdown>
    )
}
