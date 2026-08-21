import { useActions, useValues } from 'kea'

import {
    IconArchive,
    IconBuilding,
    IconChevronDown,
    IconFlag,
    IconFolder,
    IconRefresh,
    IconSort,
    IconTarget,
} from '@posthog/icons'
import { LemonButton, LemonMenu, LemonMenuItems } from '@posthog/lemon-ui'

import { MemberSelectMultiplePopover } from 'lib/components/MemberSelectMultiplePopover'

import {
    FEATURE_REQUEST_ARCHIVE_OPTIONS,
    FEATURE_REQUEST_ORDERING_OPTIONS,
    FEATURE_REQUEST_PRIORITY_FILTER_OPTIONS,
    FEATURE_REQUEST_STATUS_OPTIONS,
} from './featureRequestOptions'
import { featureRequestsLogic } from './featureRequestsLogic'

export function FeatureRequestFilters(): JSX.Element {
    const {
        statusFilter,
        priorityFilter,
        productAreaFilter,
        accountFilter,
        createdByFilter,
        archiveState,
        requestOrdering,
        productAreas,
        accounts,
        featureRequestsResponseLoading,
        hasActiveFilters,
    } = useValues(featureRequestsLogic)
    const {
        toggleStatusFilter,
        togglePriorityFilter,
        toggleProductAreaFilter,
        toggleAccountFilter,
        setCreatedByFilter,
        setArchiveState,
        setRequestOrdering,
        clearFilters,
        loadFeatureRequests,
    } = useActions(featureRequestsLogic)

    const statusItems: LemonMenuItems = [
        {
            items: FEATURE_REQUEST_STATUS_OPTIONS.map((option) => ({
                label: option.label,
                active: statusFilter.includes(option.value),
                onClick: () => toggleStatusFilter(option.value),
            })),
        },
    ]
    const priorityItems: LemonMenuItems = [
        {
            items: FEATURE_REQUEST_PRIORITY_FILTER_OPTIONS.map((option) => ({
                label: option.label,
                active: priorityFilter.includes(option.value),
                onClick: () => togglePriorityFilter(option.value),
            })),
        },
    ]
    const productAreaItems: LemonMenuItems = [
        {
            items: productAreas.map((area) => ({
                label: area.is_active ? area.name : `${area.name} (inactive)`,
                active: productAreaFilter.includes(area.id),
                onClick: () => toggleProductAreaFilter(area.id),
            })),
        },
    ]
    const accountItems: LemonMenuItems = [
        {
            items: accounts.map((account) => ({
                label: account.name,
                active: accountFilter.includes(account.id),
                onClick: () => toggleAccountFilter(account.id),
            })),
        },
    ]
    const archiveItems: LemonMenuItems = [
        {
            items: FEATURE_REQUEST_ARCHIVE_OPTIONS.map((option) => ({
                label: option.label,
                active: archiveState === option.value,
                onClick: () => setArchiveState(option.value),
            })),
        },
    ]
    const orderingItems: LemonMenuItems = [
        {
            items: FEATURE_REQUEST_ORDERING_OPTIONS.map((option) => ({
                label: option.label,
                active: requestOrdering === option.value,
                onClick: () => setRequestOrdering(option.value),
            })),
        },
    ]

    return (
        <div className="flex items-start gap-2 w-full">
            <div className="flex flex-1 flex-wrap items-center gap-2 min-w-0">
                <LemonMenu items={orderingItems} closeOnClickInside>
                    <LemonButton type="secondary" size="small" icon={<IconSort />} sideIcon={<IconChevronDown />}>
                        {FEATURE_REQUEST_ORDERING_OPTIONS.find((option) => option.value === requestOrdering)?.label}
                    </LemonButton>
                </LemonMenu>
                <LemonMenu items={statusItems} closeOnClickInside={false}>
                    <LemonButton
                        type="secondary"
                        size="small"
                        icon={<IconTarget />}
                        sideIcon={<IconChevronDown />}
                        active={statusFilter.length > 0}
                    >
                        {statusFilter.length ? `Status · ${statusFilter.length}` : 'Status'}
                    </LemonButton>
                </LemonMenu>
                <LemonMenu items={priorityItems} closeOnClickInside={false}>
                    <LemonButton
                        type="secondary"
                        size="small"
                        icon={<IconFlag />}
                        sideIcon={<IconChevronDown />}
                        active={priorityFilter.length > 0}
                    >
                        {priorityFilter.length ? `Priority · ${priorityFilter.length}` : 'Priority'}
                    </LemonButton>
                </LemonMenu>
                <LemonMenu items={productAreaItems} closeOnClickInside={false}>
                    <LemonButton
                        type="secondary"
                        size="small"
                        icon={<IconFolder />}
                        sideIcon={<IconChevronDown />}
                        active={productAreaFilter.length > 0}
                    >
                        {productAreaFilter.length ? `Product area · ${productAreaFilter.length}` : 'Product area'}
                    </LemonButton>
                </LemonMenu>
                <LemonMenu items={accountItems} closeOnClickInside={false}>
                    <LemonButton
                        type="secondary"
                        size="small"
                        icon={<IconBuilding />}
                        sideIcon={<IconChevronDown />}
                        active={accountFilter.length > 0}
                    >
                        {accountFilter.length ? `Account · ${accountFilter.length}` : 'Account'}
                    </LemonButton>
                </LemonMenu>
                <MemberSelectMultiplePopover value={createdByFilter} onChange={setCreatedByFilter} />
                <LemonMenu items={archiveItems} closeOnClickInside>
                    <LemonButton
                        type="secondary"
                        size="small"
                        icon={<IconArchive />}
                        sideIcon={<IconChevronDown />}
                        active={archiveState !== 'active'}
                    >
                        {FEATURE_REQUEST_ARCHIVE_OPTIONS.find((option) => option.value === archiveState)?.label}
                    </LemonButton>
                </LemonMenu>
            </div>
            <div className="flex shrink-0 items-center gap-2 ml-auto">
                {hasActiveFilters && (
                    <LemonButton type="tertiary" size="small" onClick={clearFilters}>
                        Clear filters
                    </LemonButton>
                )}
                <LemonButton
                    type="secondary"
                    size="small"
                    icon={<IconRefresh />}
                    loading={featureRequestsResponseLoading}
                    tooltip="Refresh"
                    aria-label="Refresh feature requests"
                    onClick={loadFeatureRequests}
                />
            </div>
        </div>
    )
}
