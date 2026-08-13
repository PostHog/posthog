import { useActions, useValues } from 'kea'
import { combineUrl } from 'kea-router'

import { LemonBanner, LemonButton, LemonTable, LemonTableColumns, LemonTag, Link } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'
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
    } = useValues(featureRequestsLogic)
    const { openCreateRequest, openProductAreas, setFeatureRequestsPage, loadFeatureRequests } =
        useActions(featureRequestsLogic)

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
            title: 'Account',
            key: 'account',
            render: (_, request) => request.account.name,
        },
        {
            title: 'Product areas',
            key: 'product_areas',
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
            key: 'request_status',
            render: (_, request) => <FeatureRequestStatusBadge status={request.request_status} />,
        },
        {
            title: 'Priority',
            key: 'request_priority',
            render: (_, request) => <FeatureRequestPriorityBadge priority={request.request_priority} />,
        },
        {
            title: 'Updated',
            key: 'updated_at',
            render: (_, request) => <TZLabel time={request.updated_at} />,
        },
    ]

    return (
        <div className="@container mx-auto w-full max-w-6xl flex flex-col gap-4 px-6 py-4">
            <div className="flex flex-wrap items-center justify-between gap-2">
                <FeatureRequestFilters />
            </div>
            <div className="flex items-center justify-end gap-2">
                <LemonButton type="secondary" onClick={openProductAreas} disabledReason={managerDisabledReason}>
                    Manage product areas
                </LemonButton>
                <LemonButton
                    type="primary"
                    onClick={openCreateRequest}
                    disabledReason={editorDisabledReason}
                    data-attr="new-feature-request"
                >
                    New request
                </LemonButton>
            </div>
            {featureRequestsError && (
                <LemonBanner type="error" action={{ children: 'Try again', onClick: loadFeatureRequests }}>
                    {featureRequestsError}
                </LemonBanner>
            )}
            <LemonTable
                dataSource={featureRequestsResponse.results}
                columns={columns}
                rowKey="id"
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
