import { useActions, useValues } from 'kea'

import { IconCheck, IconChevronDown, IconX } from '@posthog/icons'
import {
    LemonButton,
    LemonCheckbox,
    LemonDivider,
    LemonDropdown,
    LemonInput,
    LemonInputSelect,
    LemonSnack,
} from '@posthog/lemon-ui'

import { MemberSelectMultiple } from 'lib/components/MemberSelectMultiple'

import { tagsModel } from '~/models/tagsModel'

import { announcementsLogic } from './announcementsLogic'

export function AnnouncementAccountFilters(): JSX.Element {
    const {
        accountSearch,
        accountTags,
        assignedTo,
        allUnassigned,
        assignedToCurrentUser,
        filtersActive,
        filteredChannels,
        filteredAccountChannelIdsLoading,
        selectedChannelIds,
    } = useValues(announcementsLogic)
    const {
        setAccountSearch,
        setAccountTags,
        setAssignedTo,
        setAllUnassigned,
        setMyAccounts,
        clearAccountFilters,
        selectAllFilteredChannels,
        toggleChannel,
    } = useActions(announcementsLogic)
    const { tags: tagsAvailable } = useValues(tagsModel)

    const tagsButtonLabel =
        accountTags.length === 0 ? 'All tags' : accountTags.length === 1 ? accountTags[0] : `${accountTags.length} tags`
    const assignedButtonLabel = allUnassigned
        ? 'Unassigned'
        : assignedTo.length === 0
          ? 'Assigned to anyone'
          : assignedTo.length === 1
            ? 'Assigned to 1 person'
            : `Assigned to ${assignedTo.length} people`

    const matchCountLabel = filteredAccountChannelIdsLoading
        ? 'Finding matching channels…'
        : `${filteredChannels.length} ${filteredChannels.length === 1 ? 'channel matches' : 'channels match'}`

    return (
        <div className="flex flex-col gap-2">
            <div className="flex flex-wrap gap-2 items-center">
                <LemonInput
                    type="search"
                    placeholder="Filter accounts by name or ID…"
                    value={accountSearch}
                    onChange={setAccountSearch}
                    size="small"
                    className="min-w-64"
                    data-attr="announcement-accounts-search"
                />
                <LemonDropdown
                    closeOnClickInside={false}
                    overlay={
                        <div className="p-2 min-w-64">
                            <LemonInputSelect
                                mode="multiple"
                                allowCustomValues
                                value={accountTags}
                                options={(tagsAvailable || []).map((tag: string) => ({ key: tag, label: tag }))}
                                onChange={setAccountTags}
                                placeholder="Select or type tags…"
                                data-attr="announcement-accounts-tags-filter"
                            />
                        </div>
                    }
                >
                    <LemonButton type="secondary" size="small" sideIcon={<IconChevronDown />}>
                        {tagsButtonLabel}
                    </LemonButton>
                </LemonDropdown>
                <LemonDropdown
                    closeOnClickInside={false}
                    overlay={
                        <div className="p-2 min-w-64 flex flex-col gap-2">
                            <LemonCheckbox
                                checked={allUnassigned}
                                onChange={setAllUnassigned}
                                label="Unassigned only"
                                data-attr="announcement-accounts-unassigned-filter"
                            />
                            <LemonDivider className="my-0" />
                            <MemberSelectMultiple
                                idKey="id"
                                value={assignedTo}
                                onChange={(users) => setAssignedTo(users.map((user) => user.id))}
                            />
                        </div>
                    }
                >
                    <LemonButton type="secondary" size="small" sideIcon={<IconChevronDown />}>
                        {assignedButtonLabel}
                    </LemonButton>
                </LemonDropdown>
                <LemonCheckbox
                    checked={assignedToCurrentUser}
                    onChange={setMyAccounts}
                    label="My accounts"
                    data-attr="announcement-accounts-my-accounts-filter"
                />
                {filtersActive && (
                    <LemonButton
                        type="secondary"
                        size="small"
                        icon={<IconX />}
                        onClick={clearAccountFilters}
                        tooltip="Clear account filters"
                    />
                )}
            </div>
            {filtersActive && (
                <div className="flex flex-col gap-2 rounded border bg-bg-light p-2">
                    <div className="flex items-center justify-between gap-2">
                        <span className="text-sm font-medium">{matchCountLabel}</span>
                        <LemonButton
                            type="secondary"
                            size="small"
                            onClick={selectAllFilteredChannels}
                            loading={filteredAccountChannelIdsLoading}
                            disabledReason={filteredChannels.length === 0 ? 'No matching channels' : undefined}
                            data-attr="announcement-select-filtered-channels"
                        >
                            Select all
                        </LemonButton>
                    </div>
                    {!filteredAccountChannelIdsLoading && filteredChannels.length > 0 && (
                        <div className="flex max-h-32 flex-wrap gap-1 overflow-y-auto">
                            {filteredChannels.map((channel) => {
                                const isSelected = selectedChannelIds.includes(channel.key)
                                return (
                                    <LemonSnack
                                        key={channel.key}
                                        onClick={() => toggleChannel(channel.key)}
                                        className={isSelected ? 'bg-accent-highlight' : undefined}
                                        title={isSelected ? 'Click to remove' : 'Click to add'}
                                        data-attr="announcement-preview-channel"
                                    >
                                        <span className="flex items-center gap-1">
                                            {isSelected && <IconCheck className="text-accent" />}
                                            {channel.label}
                                        </span>
                                    </LemonSnack>
                                )
                            })}
                        </div>
                    )}
                    {!filteredAccountChannelIdsLoading && filteredChannels.length === 0 && (
                        <span className="text-sm text-muted">No channels the bot can post to match these filters.</span>
                    )}
                </div>
            )}
        </div>
    )
}
