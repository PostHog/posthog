import { useActions, useValues } from 'kea'

import { IconPlusSmall, IconSearch, IconX } from '@posthog/icons'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { Button, InputGroup, InputGroupAddon, InputGroupInput, Item, ItemContent, ItemTitle, Text } from 'lib/ui/quill'
import { urls } from 'scenes/urls'

import { AssigneeIconDisplay, AssigneeLabelDisplay } from './AssigneeDisplay'
import { assigneeSelectLogic } from './assigneeSelectLogic'
import { Assignee, TicketAssignee, toTicketAssignee } from './types'

export interface AssigneeDropdownProps {
    assignee: TicketAssignee
    onChange: (assignee: TicketAssignee) => void
}

export function AssigneeDropdown({ assignee, onChange }: AssigneeDropdownProps): JSX.Element {
    const { search, filteredRoles, otherFilteredMembers, currentUserMember, rolesLoading, membersLoading } =
        useValues(assigneeSelectLogic)
    const { setSearch } = useActions(assigneeSelectLogic)

    return (
        <div className="flex w-72 flex-col gap-2">
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
                {assignee ? (
                    <Item
                        variant="menuItem"
                        size="xs"
                        render={<Button variant="default" left className="w-full font-normal" />}
                        onClick={() => onChange(null)}
                    >
                        <ItemContent variant="menuItem">
                            <ItemTitle className="flex items-center gap-1">
                                <IconX />
                                Remove assignee
                            </ItemTitle>
                        </ItemContent>
                    </Item>
                ) : null}

                {currentUserMember ? (
                    <AssigneeItem
                        item={{
                            id: currentUserMember.user.id,
                            type: 'user',
                            user: currentUserMember.user,
                        }}
                        onSelect={onChange}
                        activeId={assignee?.id}
                        labelSuffix={
                            <Text size="xs" variant="muted" render={<span />}>
                                (you)
                            </Text>
                        }
                    />
                ) : null}

                <Section
                    title="Roles"
                    loading={rolesLoading}
                    search={!!search}
                    items={filteredRoles.map((role) => ({
                        id: role.id,
                        type: 'role' as const,
                        role: role,
                    }))}
                    onSelect={onChange}
                    activeId={assignee?.id}
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

                {!!search || membersLoading || otherFilteredMembers.length > 0 ? (
                    <Section
                        title="Users"
                        loading={membersLoading}
                        search={!!search}
                        items={otherFilteredMembers.map((member) => ({
                            id: member.user.id,
                            type: 'user' as const,
                            user: member.user,
                        }))}
                        onSelect={onChange}
                        activeId={assignee?.id}
                    />
                ) : null}
            </div>
        </div>
    )
}

const AssigneeItem = ({
    item,
    onSelect,
    activeId,
    labelSuffix,
}: {
    item: Assignee
    onSelect: (value: TicketAssignee) => void
    activeId?: string | number
    labelSuffix?: JSX.Element
}): JSX.Element => {
    const active = String(activeId) === String(item?.id)
    return (
        <Item
            variant="menuItem"
            size="xs"
            tone={active ? 'info' : 'default'}
            render={<Button variant="default" left className="w-full font-normal" />}
            onClick={() => item?.id && onSelect(String(activeId) === String(item.id) ? null : toTicketAssignee(item))}
        >
            <ItemContent variant="menuItem">
                <ItemTitle className="flex items-center gap-1">
                    <AssigneeIconDisplay assignee={item} />
                    <AssigneeLabelDisplay assignee={item} />
                    {labelSuffix}
                </ItemTitle>
            </ItemContent>
        </Item>
    )
}

const Section = ({
    loading,
    search,
    items,
    onSelect,
    activeId,
    emptyState,
    title,
}: {
    title: string
    loading: boolean
    search: boolean
    items: Assignee[]
    onSelect: (value: TicketAssignee) => void
    activeId?: string | number
    emptyState?: JSX.Element
}): JSX.Element => {
    return (
        <div className="flex flex-col gap-px">
            <Text size="xs" variant="muted" className="px-2 py-0.5">
                {title}
            </Text>
            {items.map((item) => (
                <AssigneeItem key={item?.id || 'unassigned'} item={item} onSelect={onSelect} activeId={activeId} />
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
