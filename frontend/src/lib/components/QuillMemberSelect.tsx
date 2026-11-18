import { useRef } from 'react'

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

import type { OrganizationMemberType, UserBasicType } from '~/types'

const NONE_KEY = 'none'
const MEMBER_PREFIX = 'member:'
const OPTION_PREFIX = 'option:'
const EXTRA_PREFIX = 'extra:'

export interface QuillMemberSelectProps {
    open: boolean
    onOpenChange: (open: boolean) => void
    searchValue: string
    onSearchChange: (query: string) => void
    members: OrganizationMemberType[]
    options?: { uuid: string; name: string; email: string; trailing?: string | number }[]
    optionsLoading?: boolean
    membersLoading: boolean
    extraOptions: { label: string; onClick: () => void }[]
    allowNone: boolean
    defaultLabel: string
    currentUserUuid?: string
    selectedUser: UserBasicType | null
    onChange: (user: UserBasicType | null) => void
    onSelectOption?: (uuid: string, name: string) => void
    onClose: () => void
    variant: 'primary' | 'outline' | 'default'
}

export function QuillMemberSelect({
    open,
    onOpenChange,
    searchValue,
    onSearchChange,
    members,
    options,
    optionsLoading,
    membersLoading,
    extraOptions,
    allowNone,
    defaultLabel,
    currentUserUuid,
    selectedUser,
    onChange,
    onSelectOption,
    onClose,
    variant,
}: QuillMemberSelectProps): JSX.Element {
    const triggerRef = useRef<HTMLButtonElement>(null)

    // You come first in a caller's own options too, unless a search has reordered them.
    const displayedOptions =
        options && !searchValue && currentUserUuid
            ? [...options].sort(
                  (first, second) => Number(second.uuid === currentUserUuid) - Number(first.uuid === currentUserUuid)
              )
            : options

    const membersByKey = new Map(members.map((member) => [`${MEMBER_PREFIX}${member.user.uuid}`, member]))
    const optionsByKey = new Map((displayedOptions ?? []).map((option) => [`${OPTION_PREFIX}${option.uuid}`, option]))
    const extrasByKey = new Map(extraOptions.map((option) => [`${EXTRA_PREFIX}${option.label}`, option]))
    const items = [
        ...(allowNone ? [NONE_KEY] : []),
        ...membersByKey.keys(),
        ...optionsByKey.keys(),
        ...extrasByKey.keys(),
    ]
    const loading = options ? optionsLoading : membersLoading

    const selectItem = (key: string | null): void => {
        if (!key) {
            return
        }

        if (key === NONE_KEY) {
            onChange(null)
            return
        }

        const member = membersByKey.get(key)
        if (member) {
            onChange(member.user)
            return
        }

        const option = optionsByKey.get(key)
        if (option) {
            onClose()
            onSelectOption?.(option.uuid, option.name || option.email)
            return
        }

        const extra = extrasByKey.get(key)
        if (extra) {
            onClose()
            extra.onClick()
        }
    }

    return (
        <Combobox<string>
            items={items}
            filter={null}
            open={open}
            onOpenChange={onOpenChange}
            value={null}
            onValueChange={selectItem}
            inputValue={searchValue}
            onInputValueChange={(query, eventDetails) => {
                if (eventDetails.reason === 'input-change') {
                    onSearchChange(query)
                }
            }}
        >
            <Button ref={triggerRef} variant={variant} className="min-w-0" onClick={() => onOpenChange(!open)}>
                <span className="ph-no-capture min-w-0 truncate">
                    {selectedUser
                        ? `${fullName(selectedUser)}${currentUserUuid === selectedUser.uuid ? ' (you)' : ''}`
                        : defaultLabel}
                </span>
                <SelectTriggerIcon />
            </Button>
            <ComboboxContent anchor={triggerRef} className="w-64">
                <ComboboxInput placeholder="Search" showTrigger={false} />
                <ComboboxEmpty>
                    {loading ? (
                        <span className="flex items-center gap-2">
                            <Spinner />
                            Loading...
                        </span>
                    ) : searchValue ? (
                        'No matches'
                    ) : (
                        'No users'
                    )}
                </ComboboxEmpty>
                <ComboboxList>
                    {(key: string) => {
                        if (key === NONE_KEY) {
                            return (
                                <ComboboxItem key={key} value={key}>
                                    {defaultLabel}
                                </ComboboxItem>
                            )
                        }

                        const member = membersByKey.get(key)
                        if (member) {
                            return (
                                <ComboboxItem key={key} value={key}>
                                    <span className="ph-no-capture flex min-w-0 items-center gap-2">
                                        <QuillPersonAvatar
                                            name={fullName(member.user)}
                                            email={member.user.email}
                                            size="xs"
                                        />
                                        <span className="truncate">
                                            {`${fullName(member.user)}${member.user.uuid === currentUserUuid ? ' (you)' : ''}`}
                                        </span>
                                    </span>
                                </ComboboxItem>
                            )
                        }

                        const option = optionsByKey.get(key)
                        if (option) {
                            return (
                                <ComboboxItem key={key} value={key}>
                                    <span className="ph-no-capture flex min-w-0 flex-1 items-center gap-2">
                                        <QuillPersonAvatar
                                            name={option.name || option.email}
                                            email={option.email}
                                            size="xs"
                                        />
                                        <span className="min-w-0 flex-1 truncate">{option.name || option.email}</span>
                                        <span className="shrink-0 text-muted-foreground">{option.trailing}</span>
                                    </span>
                                </ComboboxItem>
                            )
                        }

                        return (
                            <ComboboxItem key={key} value={key}>
                                {extrasByKey.get(key)?.label}
                            </ComboboxItem>
                        )
                    }}
                </ComboboxList>
            </ComboboxContent>
        </Combobox>
    )
}
