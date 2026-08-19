import { useActions, useValues } from 'kea'
import { combineUrl } from 'kea-router'

import { IconPlus } from '@posthog/icons'
import {
    LemonBanner,
    LemonButton,
    LemonModal,
    LemonSelect,
    LemonTable,
    LemonTableColumns,
    Link,
} from '@posthog/lemon-ui'

import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'
import { urls } from 'scenes/urls'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import type { FeatureRequestApi } from '../../generated/api.schemas'
import { accountFeatureRequestsLogic } from './accountFeatureRequestsLogic'

export function AccountFeatureRequestsExpansion({ accountId }: { accountId: string }): JSX.Element {
    const logic = accountFeatureRequestsLogic({ accountId })
    const {
        accountRequests,
        accountRequestsLoading,
        accountRequestsError,
        requestPickerOpen,
        selectedRequestId,
        candidateOptions,
        availableRequestsLoading,
        linkingRequest,
    } = useValues(logic)
    const { loadAccountRequests, openRequestPicker, closeRequestPicker, setSelectedRequestId, linkSelectedRequest } =
        useActions(logic)

    const editorDisabledReason = getAccessControlDisabledReason(
        AccessControlResourceType.CustomerAnalytics,
        AccessControlLevel.Editor
    )

    const columns: LemonTableColumns<FeatureRequestApi> = [
        {
            title: 'Request',
            key: 'title',
            render: (_, request) => (
                <Link to={urls.customerAnalyticsFeatureRequests(request.id)} className="font-medium">
                    {request.title}
                </Link>
            ),
        },
        {
            title: 'Evidence',
            key: 'evidence',
            render: (_, request) => {
                const accountLink = request.account_links.find((link) => link.account.id === accountId)
                const count = accountLink?.evidence.length ?? 0
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
                    to={
                        combineUrl(urls.customerAnalyticsFeatureRequests(request.id), {
                            evidence_account: accountId,
                        }).url
                    }
                    disabledReason={editorDisabledReason}
                >
                    Add evidence
                </LemonButton>
            ),
        },
    ]

    return (
        <div className="flex flex-col gap-3" data-attr="account-feature-requests">
            <div className="flex justify-end">
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
                dataSource={accountRequests}
                columns={columns}
                rowKey="id"
                loading={accountRequestsLoading}
                emptyState="No feature requests linked to this account."
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
                <LemonSelect
                    value={selectedRequestId}
                    onChange={setSelectedRequestId}
                    options={candidateOptions}
                    loading={availableRequestsLoading}
                    placeholder="Select a feature request"
                    fullWidth
                />
            </LemonModal>
        </div>
    )
}
