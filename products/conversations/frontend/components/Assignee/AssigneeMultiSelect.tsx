import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { IconPerson, IconPlusSmall, IconSearch, IconX } from '@posthog/icons'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import {
    Button,
    ButtonGroup,
    ItemCheckbox,
    ItemContent,
    ItemTitle,
    InputGroup,
    InputGroupAddon,
    InputGroupInput,
    Popover,
    PopoverContent,
    PopoverTrigger,
    SelectTriggerIcon,
    Text,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
} from 'lib/ui/quill'
import { urls } from 'scenes/urls'

import { AssigneeIconDisplay, AssigneeLabelDisplay, AssigneeResolver } from './AssigneeDisplay'
import { assigneeSelectLogic } from './assigneeSelectLogic'
import {
    Assignee,
    AssigneeFilterEntry,
    isSameAssigneeEntry,
    MAX_ASSIGNEE_FILTER_ENTRIES,
    toTicketAssignee,
} from './types'

export function AssigneeMultiSelect({
    value,
    onChange,
    emptyLabel = 'All assignees',
}: {
    value: AssigneeFilterEntry[]
    onChange: (value: AssigneeFilterEntry[]) => void
    emptyLabel?: string
}): JSX.Element {
    const { search, filteredRoles, filteredMembers, currentUserMember, rolesLoading, membersLoading } =
        useValues(assigneeSelectLogic)
    const { setSearch, ensureAssigneeTypesLoaded } = useActions(assigneeSelectLogic)
    const [open, setOpen] = useState(false)

    useEffect(() => {
        ensureAssigneeTypesLoaded()
    }, [ensureAssigneeTypesLoaded])

    const isSelected = (entry: AssigneeFilterEntry): boolean =>
        value.some((selected) => isSameAssigneeEntry(selected, entry))
    const toggleEntry = (entry: AssigneeFilterEntry): void => {
        onChange(
            isSelected(entry) ? value.filter((selected) => !isSameAssigneeEntry(selected, entry)) : [...value, entry]
        )
    }
    const selectionCapReason =
        value.length >= MAX_ASSIGNEE_FILTER_ENTRIES
            ? `You can select up to ${MAX_ASSIGNEE_FILTER_ENTRIES} assignees`
            : undefined

    return (
        <ButtonGroup className="w-full">
            <Popover
                open={open}
                onOpenChange={(nextOpen) => {
                    setOpen(nextOpen)
                    if (!nextOpen) {
                        setSearch('')
                    }
                }}
            >
                <PopoverTrigger render={<Button variant="outline" size="sm" className="min-w-0 flex-1" left />}>
                    <TriggerLabel value={value} emptyLabel={emptyLabel} />
                    {value.length === 0 ? <SelectTriggerIcon /> : null}
                </PopoverTrigger>
                <PopoverContent align="start" className="w-72 p-1">
                    <div className="flex flex-col gap-2">
                        <InputGroup>
                            <InputGroupAddon>
                                <IconSearch />
                            </InputGroupAddon>
                            <InputGroupInput
                                type="search"
                                placeholder="Search"
                                autoFocus
                                value={search}
                                onChange={(event) => setSearch(event.target.value)}
                            />
                        </InputGroup>
                        <div className="flex flex-col gap-px">
                            {currentUserMember ? (
                                <ItemCheckbox
                                    size="xs"
                                    aria-checked={isSelected('me')}
                                    disabled={!isSelected('me') && !!selectionCapReason}
                                    title={isSelected('me') ? undefined : selectionCapReason}
                                    onClick={() => toggleEntry('me')}
                                >
                                    <ItemContent variant="menuItem">
                                        <ItemTitle className="flex items-center gap-1">
                                            <MeIcon />
                                            Me
                                            <Text size="xs" variant="muted" render={<span />}>
                                                (current user)
                                            </Text>
                                        </ItemTitle>
                                    </ItemContent>
                                </ItemCheckbox>
                            ) : null}
                            <ItemCheckbox
                                size="xs"
                                aria-checked={isSelected('unassigned')}
                                disabled={!isSelected('unassigned') && !!selectionCapReason}
                                title={isSelected('unassigned') ? undefined : selectionCapReason}
                                onClick={() => toggleEntry('unassigned')}
                            >
                                <ItemContent variant="menuItem">
                                    <ItemTitle className="flex items-center gap-1">
                                        <AssigneeIconDisplay assignee={null} size="small" />
                                        Unassigned
                                    </ItemTitle>
                                </ItemContent>
                            </ItemCheckbox>
                            <Section
                                title="Roles"
                                loading={rolesLoading}
                                search={!!search}
                                items={filteredRoles.map((role) => ({ id: role.id, type: 'role' as const, role }))}
                                isSelected={isSelected}
                                onToggle={toggleEntry}
                                selectionCapReason={selectionCapReason}
                                emptyState={
                                    <Button
                                        variant="default"
                                        size="sm"
                                        left
                                        className="w-full"
                                        render={<LinkPrimitive to={urls.settings('organization-roles')} />}
                                    >
                                        <IconPlusSmall />
                                        <Text size="sm" variant="muted" render={<span />}>
                                            Create role
                                        </Text>
                                    </Button>
                                }
                            />
                            {!!search || membersLoading || filteredMembers.length > 0 ? (
                                <Section
                                    title="Users"
                                    loading={membersLoading}
                                    search={!!search}
                                    // Include the current user here too (as their concrete
                                    // user:<id>), so they can filter to their own UUID
                                    // specifically — distinct from the dynamic "Me" row above.
                                    items={filteredMembers.map((member) => ({
                                        id: member.user.id,
                                        type: 'user' as const,
                                        user: member.user,
                                    }))}
                                    isSelected={isSelected}
                                    onToggle={toggleEntry}
                                    selectionCapReason={selectionCapReason}
                                />
                            ) : null}
                        </div>
                    </div>
                </PopoverContent>
            </Popover>
            {value.length > 0 ? (
                <Tooltip>
                    <TooltipTrigger
                        render={
                            <Button
                                variant="outline"
                                size="icon-sm"
                                aria-label="Clear assignee filter"
                                onClick={() => onChange([])}
                            />
                        }
                    >
                        <IconX />
                    </TooltipTrigger>
                    <TooltipContent>Clear assignee filter</TooltipContent>
                </Tooltip>
            ) : null}
        </ButtonGroup>
    )
}

function TriggerLabel({ value, emptyLabel }: { value: AssigneeFilterEntry[]; emptyLabel: string }): JSX.Element {
    if (value.length === 0) {
        return <>{emptyLabel}</>
    }
    if (value.length > 1) {
        return <>{value.length} assignees</>
    }
    const entry = value[0]
    if (entry === 'unassigned') {
        return (
            <span className="flex items-center gap-1">
                <AssigneeIconDisplay assignee={null} size="small" />
                <AssigneeLabelDisplay assignee={null} size="small" />
            </span>
        )
    }
    if (entry === 'me') {
        return (
            <span className="flex items-center gap-1">
                <MeIcon />
                Me
            </span>
        )
    }
    return (
        <AssigneeResolver assignee={toTicketAssignee(entry)}>
            {({ assignee }) => (
                <span className="flex items-center gap-1">
                    <AssigneeIconDisplay assignee={assignee} size="small" />
                    <AssigneeLabelDisplay assignee={assignee} size="small" placeholder="1 assignee" />
                </span>
            )}
        </AssigneeResolver>
    )
}

// Solid person glyph for the dynamic "me" entry — distinct from the dashed
// "unassigned" icon and from any specific member's avatar.
function MeIcon(): JSX.Element {
    return <IconPerson className="rounded-full bg-accent-highlight text-accent p-0.5 h-4 w-4" />
}

const AssigneeFilterItem = ({
    item,
    isSelected,
    onToggle,
    selectionCapReason,
}: {
    item: NonNullable<Assignee>
    isSelected: (entry: AssigneeFilterEntry) => boolean
    onToggle: (entry: AssigneeFilterEntry) => void
    selectionCapReason?: string
}): JSX.Element => {
    const checked = isSelected(item)
    return (
        <ItemCheckbox
            size="xs"
            aria-checked={checked}
            disabled={!checked && !!selectionCapReason}
            title={checked ? undefined : selectionCapReason}
            onClick={() => onToggle(toTicketAssignee(item))}
        >
            <ItemContent variant="menuItem">
                <ItemTitle className="flex items-center gap-1">
                    <AssigneeIconDisplay assignee={item} size="small" />
                    <AssigneeLabelDisplay assignee={item} />
                </ItemTitle>
            </ItemContent>
        </ItemCheckbox>
    )
}

const Section = ({
    title,
    loading,
    search,
    items,
    isSelected,
    onToggle,
    selectionCapReason,
    emptyState,
}: {
    title: string
    loading: boolean
    search: boolean
    items: NonNullable<Assignee>[]
    isSelected: (entry: AssigneeFilterEntry) => boolean
    onToggle: (entry: AssigneeFilterEntry) => void
    selectionCapReason?: string
    emptyState?: JSX.Element
}): JSX.Element => {
    return (
        <div className="flex flex-col gap-px">
            <Text size="xs" variant="muted" className="px-2 py-0.5">
                {title}
            </Text>
            {items.map((item) => (
                <AssigneeFilterItem
                    key={item.id}
                    item={item}
                    isSelected={isSelected}
                    onToggle={onToggle}
                    selectionCapReason={selectionCapReason}
                />
            ))}
            {loading ? (
                <Text size="sm" variant="muted" className="italic px-2 py-2 border-t">
                    Loading...
                </Text>
            ) : items.length === 0 ? (
                search ? (
                    <Text size="sm" variant="muted" className="italic px-2 py-2 border-t">
                        No matches
                    </Text>
                ) : (
                    <div className="border-t pt-1">{emptyState}</div>
                )
            ) : null}
        </div>
    )
}
