import { useActions, useValues } from 'kea'
import { combineUrl } from 'kea-router'

import { IconSearch } from '@posthog/icons'
import {
    LemonBanner,
    LemonButton,
    LemonInput,
    LemonSkeleton,
    LemonTable,
    LemonTableColumns,
    LemonTag,
    Link,
    ProfilePicture,
} from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'
import { fullName } from 'lib/utils/strings'
import { urls } from 'scenes/urls'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import type { FeatureRequestApi } from '../../generated/api.schemas'
import { FeatureRequestCreateModal } from './FeatureRequestCreateModal'
import { FeatureRequestFilters } from './FeatureRequestFilters'
import { FeatureRequestPriorityBadge } from './FeatureRequestPriorityBadge'
import { FeatureRequestProductAreasModal } from './FeatureRequestProductAreasModal'
import { FEATURE_REQUESTS_PAGE_SIZE, featureRequestsLogic } from './featureRequestsLogic'
import { FeatureRequestStatusBadge } from './FeatureRequestStatusBadge'

export function FeatureRequestList(): JSX.Element {
    const {
        featureRequestsResponse,
        featureRequestsResponseLoading,
        featureRequestsError,
        featureRequestsPage,
        hasActiveFilters,
        listSearchParams,
        searchQuery,
        creatorById,
        members,
        tableSorting,
    } = useValues(featureRequestsLogic)
    const {
        openCreateRequest,
        openProductAreas,
        setFeatureRequestsPage,
        loadFeatureRequests,
        setSearchQuery,
        setTableSorting,
    } = useActions(featureRequestsLogic)

    const editorDisabledReason = getAccessControlDisabledReason(
        AccessControlResourceType.CustomerAnalytics,
        AccessControlLevel.Editor
    )
    const managerDisabledReason = getAccessControlDisabledReason(
        AccessControlResourceType.CustomerAnalytics,
        AccessControlLevel.Manager
    )

    const columns: LemonTableColumns<FeatureRequestApi> = [
        {
            title: 'Request',
            key: 'title',
            sorter: true,
            render: (_, request) => (
                <div className="flex flex-col gap-1 py-1">
                    <Link
                        to={combineUrl(urls.customerAnalyticsFeatureRequests(request.id), listSearchParams).url}
                        className="font-semibold"
                    >
                        {request.title}
                    </Link>
                    {request.is_archived && <LemonTag type="muted">Archived</LemonTag>}
                </div>
            ),
        },
        {
            title: 'Accounts',
            key: 'account',
            sorter: true,
            render: (_, request) => request.account_links.map((link) => link.account.name).join(', '),
        },
        {
            title: 'Product areas',
            key: 'product_area',
            sorter: true,
            render: (_, request) => (
                <div className="flex flex-wrap gap-1">
                    {request.product_areas.map((area) => (
                        <LemonTag key={area.id}>{area.name}</LemonTag>
                    ))}
                </div>
            ),
        },
        {
            title: 'Status',
            key: 'status',
            sorter: true,
            render: (_, request) => <FeatureRequestStatusBadge status={request.request_status} />,
        },
        {
            title: 'Priority',
            key: 'priority',
            sorter: true,
            defaultSortOrder: -1,
            render: (_, request) => <FeatureRequestPriorityBadge priority={request.request_priority} />,
        },
        {
            title: 'Evidence',
            key: 'evidence_count',
            sorter: true,
            align: 'right',
            defaultSortOrder: -1,
            render: (_, request) => request.evidence_count,
        },
        {
            title: 'Created by',
            key: 'created_by',
            sorter: true,
            render: (_, request) => {
                if (request.created_by === null) {
                    return <span className="text-muted">—</span>
                }
                if (members === null) {
                    return <LemonSkeleton className="w-24 h-4" />
                }
                const creator = creatorById[request.created_by]
                return creator ? (
                    <div className="flex items-center gap-2">
                        <ProfilePicture user={creator} size="sm" />
                        <span className="whitespace-nowrap">{fullName(creator) || creator.email}</span>
                    </div>
                ) : (
                    <span className="text-muted">Unknown user</span>
                )
            },
        },
        {
            title: 'Updated',
            key: 'updated_at',
            sorter: true,
            defaultSortOrder: -1,
            render: (_, request) => <TZLabel time={request.updated_at} />,
        },
    ]

    return (
        <div className="@container w-full flex flex-col gap-4">
            <div className="flex flex-wrap items-center gap-2 w-full">
                <LemonInput
                    className="flex-1 min-w-56 max-w-[640px] [&_.LemonInput__input]:pr-4"
                    type="search"
                    value={searchQuery}
                    onChange={setSearchQuery}
                    placeholder="Search by title or description"
                    prefix={<IconSearch />}
                    size="small"
                    data-attr="feature-request-search"
                />
                <div className="flex items-center gap-2 ml-auto">
                    <LemonButton
                        type="secondary"
                        size="small"
                        onClick={openProductAreas}
                        disabledReason={managerDisabledReason}
                    >
                        Manage product areas
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        size="small"
                        onClick={openCreateRequest}
                        disabledReason={editorDisabledReason}
                        data-attr="new-feature-request"
                    >
                        New request
                    </LemonButton>
                </div>
            </div>
            <FeatureRequestFilters />
            {featureRequestsError && (
                <LemonBanner type="error" action={{ children: 'Try again', onClick: loadFeatureRequests }}>
                    {featureRequestsError}
                </LemonBanner>
            )}
            <LemonTable
                dataSource={featureRequestsResponse.results}
                columns={columns}
                rowKey="id"
                sorting={tableSorting}
                onSort={setTableSorting}
                useURLForSorting={false}
                noSortingCancellation
                loading={featureRequestsResponseLoading}
                emptyState={hasActiveFilters ? 'No feature requests match these filters' : 'No feature requests yet'}
                nouns={['feature request', 'feature requests']}
                pagination={{
                    controlled: true,
                    currentPage: featureRequestsPage,
                    pageSize: FEATURE_REQUESTS_PAGE_SIZE,
                    entryCount: featureRequestsResponse.count,
                    onBackward:
                        featureRequestsPage > 1 ? () => setFeatureRequestsPage(featureRequestsPage - 1) : undefined,
                    onForward:
                        featureRequestsPage * FEATURE_REQUESTS_PAGE_SIZE < featureRequestsResponse.count
                            ? () => setFeatureRequestsPage(featureRequestsPage + 1)
                            : undefined,
                }}
            />
            <FeatureRequestCreateModal />
            <FeatureRequestProductAreasModal />
        </div>
    )
}
