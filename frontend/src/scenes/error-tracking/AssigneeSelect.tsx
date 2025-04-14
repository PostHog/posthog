import { IconPlusSmall, IconX } from '@posthog/icons'
import { LemonButton, LemonButtonProps, LemonDropdown, LemonInput } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'
import { urls } from 'scenes/urls'

import { ErrorTrackingIssue, ErrorTrackingIssueAssignee } from '~/queries/schema/schema-general'

import { AssigneeDisplay } from './AssigneeDisplay'
import { AssigneeDisplayType, assigneeSelectLogic } from './assigneeSelectLogic'

export const AssigneeSelect = ({
    assignee,
    onChange,
    showName = false,
    showIcon = true,
    allowRemoval = true,
    unassignedLabel = 'Unassigned',
    ...buttonProps
}: {
    assignee: ErrorTrackingIssue['assignee']
    onChange: (assignee: ErrorTrackingIssue['assignee']) => void
    showName?: boolean
    showIcon?: boolean
    allowRemoval?: boolean
    unassignedLabel?: string
} & Partial<Pick<LemonButtonProps, 'type' | 'size' | 'fullWidth'>>): JSX.Element => {
    const { search, groupOptions, memberOptions, userGroupsLoading, membersLoading } = useValues(assigneeSelectLogic)
    const { setSearch, ensureAssigneeTypesLoaded } = useActions(assigneeSelectLogic)
    const [showPopover, setShowPopover] = useState(false)

    const _onChange = (value: ErrorTrackingIssue['assignee']): void => {
        setSearch('')
        setShowPopover(false)
        onChange(value)
    }

    useEffect(() => {
        ensureAssigneeTypesLoaded()
    }, [ensureAssigneeTypesLoaded])

    return (
        <LemonDropdown
            closeOnClickInside={false}
            visible={showPopover}
            matchWidth={false}
            onVisibilityChange={(visible) => setShowPopover(visible)}
            overlay={
                <div className="max-w-100 deprecated-space-y-2 overflow-hidden">
                    <LemonInput
                        type="search"
                        placeholder="Search"
                        autoFocus
                        value={search}
                        onChange={setSearch}
                        fullWidth
                    />
                    <ul className="deprecated-space-y-2">
                        {assignee && allowRemoval ? (
                            <li>
                                <LemonButton
                                    fullWidth
                                    role="menuitem"
                                    size="small"
                                    icon={<IconX />}
                                    onClick={() => _onChange(null)}
                                >
                                    Remove assignee
                                </LemonButton>
                            </li>
                        ) : null}

                        <Section
                            title="Groups"
                            loading={userGroupsLoading}
                            search={!!search}
                            type="user_group"
                            items={groupOptions}
                            onSelect={_onChange}
                            activeId={assignee?.id}
                            emptyState={
                                <LemonButton
                                    fullWidth
                                    size="small"
                                    icon={<IconPlusSmall />}
                                    to={urls.settings('environment-error-tracking', 'user-groups')}
                                >
                                    <div className="text-secondary">Create user group</div>
                                </LemonButton>
                            }
                        />

                        <Section
                            title="Users"
                            loading={membersLoading}
                            search={!!search}
                            type="user"
                            items={memberOptions}
                            onSelect={_onChange}
                            activeId={assignee?.id}
                        />
                    </ul>
                </div>
            }
        >
            <div>
                <AssigneeDisplay assignee={assignee}>
                    {({ displayAssignee }) => (
                        <LemonButton
                            tooltip={displayAssignee.displayName}
                            icon={showIcon ? displayAssignee.icon : null}
                            {...buttonProps}
                        >
                            {showName ? (
                                <span className="pl-1">
                                    {displayAssignee.id === 'unassigned'
                                        ? unassignedLabel
                                        : displayAssignee.displayName}
                                </span>
                            ) : null}
                        </LemonButton>
                    )}
                </AssigneeDisplay>
            </div>
        </LemonDropdown>
    )
}

const Section = ({
    loading,
    search,
    type,
    items,
    onSelect,
    activeId,
    emptyState,
    title,
}: {
    title: string
    loading: boolean
    search: boolean
    type: ErrorTrackingIssueAssignee['type']
    items: AssigneeDisplayType[]
    onSelect: (value: ErrorTrackingIssue['assignee']) => void
    activeId?: string | number
    emptyState?: JSX.Element
}): JSX.Element => {
    return (
        <li>
            <section className="deprecated-space-y-px">
                <h5 className="mx-2 my-0.5">{title}</h5>
                {items.map((item) => (
                    <li key={item.id}>
                        <LemonButton
                            fullWidth
                            role="menuitem"
                            size="small"
                            icon={item.icon}
                            onClick={() => onSelect(activeId === item.id ? null : { type, id: item.id })}
                            active={activeId === item.id}
                        >
                            <span className="flex items-center justify-between gap-2 flex-1">
                                <span>{item.displayName}</span>
                            </span>
                        </LemonButton>
                    </li>
                ))}

                {loading ? (
                    <div className="p-2 text-secondary italic truncate border-t">Loading...</div>
                ) : items.length === 0 ? (
                    search ? (
                        <div className="p-2 text-secondary italic truncate border-t">
                            <span>No matches</span>
                        </div>
                    ) : (
                        <div className="border-t pt-1">{emptyState}</div>
                    )
                ) : null}
            </section>
        </li>
    )
}
