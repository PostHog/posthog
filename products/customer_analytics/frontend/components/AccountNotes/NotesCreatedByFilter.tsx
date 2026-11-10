import { IconChevronDown, IconX } from '@posthog/icons'
import { LemonButton, LemonDropdown } from '@posthog/lemon-ui'

import { MemberSelectMultiple } from 'lib/components/MemberSelectMultiple'

interface NotesCreatedByFilterProps {
    value: number[]
    onChange: (userIds: number[]) => void
}

// The author filter shared by the team Notes tab and an account's Notes tab, so a saved view's author filter means the same in both.
export function NotesCreatedByFilter({ value, onChange }: NotesCreatedByFilterProps): JSX.Element {
    const buttonLabel =
        value.length === 0
            ? 'Created by anyone'
            : value.length === 1
              ? 'Created by 1 person'
              : `Created by ${value.length} people`
    return (
        <div className="flex gap-1 items-center" data-attr="account-notes-created-by-filter">
            <LemonDropdown
                closeOnClickInside={false}
                overlay={
                    <div className="p-2 min-w-64">
                        <MemberSelectMultiple
                            idKey="id"
                            value={value}
                            onChange={(users) => onChange(users.map((user) => user.id))}
                        />
                    </div>
                }
            >
                <LemonButton type="secondary" size="small" sideIcon={<IconChevronDown />}>
                    {buttonLabel}
                </LemonButton>
            </LemonDropdown>
            {value.length > 0 && (
                <LemonButton
                    type="secondary"
                    size="small"
                    icon={<IconX />}
                    onClick={() => onChange([])}
                    tooltip="Clear created-by filter"
                />
            )}
        </div>
    )
}
