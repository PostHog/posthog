import { useActions, useValues } from 'kea'

import { IconPlus, IconSearch } from '@posthog/icons'
import {
    LemonBanner,
    LemonButton,
    LemonInput,
    LemonInputSelect,
    LemonModal,
    LemonTable,
    LemonTableColumns,
    Link,
} from '@posthog/lemon-ui'

import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'
import { urls } from 'scenes/urls'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import type { FeatureRequestApi } from '../../generated/api.schemas'
import { getFeatureRequestDetailUrl } from '../FeatureRequests/featureRequestNavigation'
import { ACCOUNT_FEATURE_REQUESTS_PAGE_SIZE, accountFeatureRequestsLogic } from './accountFeatureRequestsLogic'

export function AccountFeatureRequestsExpansion({ accountId }: { accountId: string }): JSX.Element {
    const logic = accountFeatureRequestsLogic({ accountId })
    const {
        accountRequests,
        accountRequestsPage,
        accountRequestsSearch,
        accountRequestsLoading,
        accountRequestsError,
        requestPickerOpen,
        selectedRequestId,
        candidateOptions,
        availableRequestsLoading,
        availableRequestsError,
        linkingRequest,
    } = useValues(logic)
    const {
        loadAccountRequests,
        loadAvailableRequests,
        openRequestPicker,
        closeRequestPicker,
        setSelectedRequestId,
        setAccountRequestsPage,
        setAccountRequestsSearch,
        setRequestSearch,
        linkSelectedRequest,
    } = useActions(logic)

    const editorDisabledReason = getAccessControlDisabledReason(
        AccessControlResourceType.CustomerAnalytics,
        AccessControlLevel.Editor
    )

    const origin = urls.customerAnalyticsAccount(accountId, 'feature_requests')
    const columns: LemonTableColumns<FeatureRequestApi> = [
        {
            title: 'Request',
            key: 'title',
            render: (_, request) => (
                <Link to={getFeatureRequestDetailUrl({ requestId: request.id, origin })} className="font-medium">
                    {request.title}
                </Link>
            ),
        },
        {
            title: 'Evidence',
            key: 'evidence',
            render: (_, request) => {
                const accountLink = request.account_links.find((link) => link.account.id === accountId)
                const count = accountLink?.evidence_count ?? 0
                return `${count} ${count === 1 ? 'item' : 'items'}`
            },
        },
        {
            title: '',
            key: 'actions',
            width: 120,
            render: (_, request) => (
                <LemonButton
                    type="secondary"
                    size="xsmall"
                    to={getFeatureRequestDetailUrl({
                        requestId: request.id,
                        origin,
                        searchParams: { evidence_account: accountId },
                    })}
                    disabledReason={editorDisabledReason}
                >
                    Add evidence
                </LemonButton>
            ),
        },
    ]

    return (
        <div className="flex flex-col gap-3" data-attr="account-feature-requests">
            <div className="flex flex-wrap items-center justify-between gap-2">
                <LemonInput
                    type="search"
                    value={accountRequestsSearch}
                    onChange={setAccountRequestsSearch}
                    placeholder="Search linked requests"
                    prefix={<IconSearch />}
                    size="small"
                    className="min-w-64"
                    data-attr="account-feature-requests-search"
                />
                <LemonButton
                    type="primary"
                    size="small"
                    icon={<IconPlus />}
                    onClick={openRequestPicker}
                    disabledReason={editorDisabledReason}
                >
                    Link request
                </LemonButton>
            </div>
            {accountRequestsError && (
                <LemonBanner type="error" action={{ children: 'Try again', onClick: loadAccountRequests }}>
                    {accountRequestsError}
                </LemonBanner>
            )}
            <LemonTable
                size="small"
                embedded
                dataSource={accountRequests.results}
                columns={columns}
                rowKey="id"
                loading={accountRequestsLoading}
                emptyState={
                    accountRequestsSearch.trim()
                        ? 'No linked feature requests match your search.'
                        : 'No feature requests linked to this account.'
                }
                pagination={{
                    controlled: true,
                    pageSize: ACCOUNT_FEATURE_REQUESTS_PAGE_SIZE,
                    currentPage: accountRequestsPage,
                    useUrl: false,
                    entryCount: accountRequests.count,
                    onForward: () => setAccountRequestsPage(accountRequestsPage + 1),
                    onBackward: () => setAccountRequestsPage(accountRequestsPage - 1),
                }}
            />
            <LemonModal
                isOpen={requestPickerOpen}
                onClose={closeRequestPicker}
                title="Link feature request"
                width={480}
                footer={
                    <>
                        <LemonButton type="secondary" onClick={closeRequestPicker}>
                            Cancel
                        </LemonButton>
                        <LemonButton
                            type="primary"
                            onClick={linkSelectedRequest}
                            loading={linkingRequest}
                            disabledReason={selectedRequestId ? undefined : 'Select a feature request'}
                        >
                            Link request
                        </LemonButton>
                    </>
                }
            >
                <div className="flex flex-col gap-3">
                    {availableRequestsError && (
                        <LemonBanner type="error" action={{ children: 'Try again', onClick: loadAvailableRequests }}>
                            {availableRequestsError}
                        </LemonBanner>
                    )}
                    <LemonInputSelect
                        mode="single"
                        value={selectedRequestId ? [selectedRequestId] : []}
                        onChange={(values) => setSelectedRequestId(values[0] ?? null)}
                        onInputChange={setRequestSearch}
                        options={candidateOptions}
                        loading={availableRequestsLoading}
                        placeholder="Search for a feature request"
                        fullWidth
                    />
                </div>
            </LemonModal>
        </div>
    )
}
