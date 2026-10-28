import { useActions, useValues } from 'kea'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import {
    Button,
    Combobox,
    ComboboxContent,
    ComboboxEmpty,
    ComboboxInput,
    ComboboxItem,
    ComboboxList,
    SelectTriggerIcon,
    Spinner,
} from '@posthog/quill'

import { QuillPersonAvatar } from 'lib/components/QuillPersonAvatar/QuillPersonAvatar'
import { fullName } from 'lib/utils/strings'
import { membersLogic } from 'scenes/organization/membersLogic'

import { UserBasicType } from '~/types'

const ANY_USER = 'any'

interface QuillActivityMemberFilterProps {
    /** The selected member's user id, or null for anyone. */
    value: UserBasicType['id'] | null
    onChange: (user: UserBasicType | null) => void
}

export function QuillActivityMemberFilter({ value, onChange }: QuillActivityMemberFilterProps): JSX.Element {
    const { meFirstMembers, membersLoading } = useValues(membersLogic)
    const { ensureAllMembersLoaded } = useActions(membersLogic)
    const [open, setOpen] = useState(false)
    const triggerRef = useRef<HTMLButtonElement>(null)

    // The trigger opens the picker through the controlled prop, which never calls onOpenChange, so both paths load.
    const setPickerOpen = useCallback(
        (next: boolean): void => {
            setOpen(next)
            if (next) {
                ensureAllMembersLoaded()
            }
        },
        [ensureAllMembersLoaded]
    )

    // A value set from the URL needs the member list to show a name rather than "Any user".
    useEffect(() => {
        if (value) {
            ensureAllMembersLoaded()
        }
    }, [value]) // oxlint-disable-line react-hooks/exhaustive-deps

    // You come first, then everyone else, as in the other member pickers. The unfiltered list, because the shared
    // member search from settings would otherwise hide members here.
    const { usersById, items } = useMemo(() => {
        const usersById: Record<string, UserBasicType> = {}
        const items = [ANY_USER]
        for (const { user } of meFirstMembers) {
            const id = String(user.id)
            usersById[id] = user
            items.push(id)
        }
        return { usersById, items }
    }, [meFirstMembers])
    const selected = value ? usersById[String(value)] : null
    const itemToStringLabel = useCallback(
        (key: string): string =>
            key === ANY_USER ? 'Any user' : `${fullName(usersById[key])} ${usersById[key]?.email ?? ''}`,
        [usersById]
    )
    const onValueChange = useCallback(
        (next: string | null): void => {
            onChange(!next || next === ANY_USER ? null : (usersById[next] ?? null))
            setOpen(false)
        },
        [onChange, usersById]
    )

    return (
        <Combobox<string>
            items={items}
            open={open}
            onOpenChange={setPickerOpen}
            value={value ? String(value) : ANY_USER}
            onValueChange={onValueChange}
            itemToStringLabel={itemToStringLabel}
        >
            <Button
                ref={triggerRef}
                variant="outline"
                className="min-w-0 shrink"
                onClick={() => setPickerOpen(!open)}
                data-attr="activity-member-filter"
            >
                <span className="ph-no-capture min-w-0 truncate">{selected ? fullName(selected) : 'Any user'}</span>
                <SelectTriggerIcon />
            </Button>
            <ComboboxContent anchor={triggerRef} className="w-64">
                <ComboboxInput placeholder="Search members…" showTrigger={false} />
                <ComboboxEmpty>
                    {membersLoading ? (
                        <span className="flex items-center gap-2">
                            <Spinner />
                            Loading members…
                        </span>
                    ) : (
                        'No matching members'
                    )}
                </ComboboxEmpty>
                <ComboboxList>
                    {(key: string) =>
                        key === ANY_USER ? (
                            <ComboboxItem key={key} value={key}>
                                Any user
                            </ComboboxItem>
                        ) : (
                            <ComboboxItem key={key} value={key}>
                                <span className="ph-no-capture flex min-w-0 items-center gap-2">
                                    <QuillPersonAvatar
                                        name={fullName(usersById[key])}
                                        email={usersById[key]?.email}
                                        size="xs"
                                    />
                                    <span className="truncate">{fullName(usersById[key])}</span>
                                </span>
                            </ComboboxItem>
                        )
                    }
                </ComboboxList>
            </ComboboxContent>
        </Combobox>
    )
}
