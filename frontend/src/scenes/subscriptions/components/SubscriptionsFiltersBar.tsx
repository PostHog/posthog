import { useActions, useValues } from 'kea'

import { LemonInput, LemonSelect } from '@posthog/lemon-ui'

import { MemberSelect } from 'lib/components/MemberSelect'

import { TargetTypeEnumApi, type SubscriptionsListTargetType } from '~/generated/core/api.schemas'

import { SubscriptionsTab, subscriptionsSceneLogic } from '../subscriptionsSceneLogic'

const CHANNEL_FILTER_OPTIONS: { label: string; value: SubscriptionsListTargetType | null }[] = [
    { label: 'All channels', value: null },
    { label: 'Email', value: TargetTypeEnumApi.Email },
    { label: 'Slack', value: TargetTypeEnumApi.Slack },
    { label: 'Webhook', value: TargetTypeEnumApi.Webhook },
]

export function SubscriptionsFiltersBar(): JSX.Element {
    const { search, createdByUuid, currentTab, targetTypeFilter } = useValues(subscriptionsSceneLogic)
    const { setSearch, setCreatedByFilter, setTargetTypeFilter } = useActions(subscriptionsSceneLogic)

    return (
        <div className="flex justify-between gap-2 flex-wrap mb-4">
            <LemonInput
                type="search"
                placeholder="Search by name"
                onChange={setSearch}
                value={search}
                size="small"
                data-attr="subscriptions-search"
                className="text-[13px] leading-snug [&_.LemonIcon]:text-[13px]"
            />
            <div className="flex items-center gap-2 flex-wrap">
                <div className="flex items-center gap-2">
                    <span>Filter to:</span>
                    <LemonSelect<SubscriptionsListTargetType | null>
                        size="small"
                        options={CHANNEL_FILTER_OPTIONS}
                        value={targetTypeFilter}
                        onChange={setTargetTypeFilter}
                        data-attr="subscriptions-channel-filter"
                    />
                </div>
                {currentTab !== SubscriptionsTab.Mine && (
                    <div className="flex items-center gap-2">
                        <span>Created by:</span>
                        <MemberSelect
                            value={createdByUuid}
                            onChange={(user) => setCreatedByFilter(user?.uuid ?? null)}
                        />
                    </div>
                )}
            </div>
        </div>
    )
}
