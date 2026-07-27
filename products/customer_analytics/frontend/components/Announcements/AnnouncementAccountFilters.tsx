import { useActions, useValues } from 'kea'

import { IconChevronDown, IconX } from '@posthog/icons'
import {
    LemonButton,
    LemonCheckbox,
    LemonDivider,
    LemonDropdown,
    LemonInput,
    LemonInputSelect,
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
        filteredChannelIds,
        filteredAccountChannelIdsLoading,
    } = useValues(announcementsLogic)
    const {
        setAccountSearch,
        setAccountTags,
        setAssignedTo,
        setAllUnassigned,
        setMyAccounts,
        clearAccountFilters,
        selectAllFilteredChannels,
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

    const selectAllLabel = filteredAccountChannelIdsLoading
        ? 'Finding channels…'
        : `Select ${filteredChannelIds.length} filtered ${filteredChannelIds.length === 1 ? 'channel' : 'channels'}`

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
                <div>
                    <LemonButton
                        type="secondary"
                        size="small"
                        onClick={selectAllFilteredChannels}
                        loading={filteredAccountChannelIdsLoading}
                        disabledReason={filteredChannelIds.length === 0 ? 'No matching channels' : undefined}
                        data-attr="announcement-select-filtered-channels"
                    >
                        {selectAllLabel}
                    </LemonButton>
                </div>
            )}
        </div>
    )
}
