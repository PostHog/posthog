import { useActions, useValues } from 'kea'

import {
    IconArchive,
    IconArrowLeft,
    IconBuilding,
    IconDocument,
    IconFolder,
    IconPencil,
    IconPlus,
} from '@posthog/icons'
import { LemonBanner, LemonButton, LemonTag } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import type { FeatureRequestApi } from '../../generated/api.schemas'
import { FeatureRequestAccountEvidenceModal } from './FeatureRequestAccountEvidenceModal'
import { FeatureRequestAccountItem } from './FeatureRequestAccountItem'
import { FeatureRequestDetailSection } from './FeatureRequestDetailSection'
import { FeatureRequestEditModal } from './FeatureRequestEditModal'
import { FeatureRequestHistorySection } from './FeatureRequestHistorySection'
import { FeatureRequestImages } from './FeatureRequestImages'
import { FeatureRequestPriorityBadge } from './FeatureRequestPriorityBadge'
import { FEATURE_REQUEST_ACCOUNT_PREVIEW_SIZE, featureRequestsLogic } from './featureRequestsLogic'
import { FeatureRequestStatusBadge } from './FeatureRequestStatusBadge'

export function FeatureRequestDetail({ request }: { request: FeatureRequestApi }): JSX.Element {
    const {
        mutatingArchive,
        featureRequestBackLabel,
        featureRequestBackUrl,
        activeRequestAccountLinks,
        activeRequestEvidenceCount,
        activeRequestImages,
        visibleActiveRequestAccountLinks,
        requestAccountsShowingAll,
        accountsEvidenceCollapsed,
    } = useValues(featureRequestsLogic)
    const {
        openEditRequest,
        openAddAccount,
        archiveActiveRequest,
        restoreActiveRequest,
        setRequestAccountsShowingAll,
        setAccountsEvidenceCollapsed,
        showHistoryTarget,
    } = useActions(featureRequestsLogic)
    const editorDisabledReason = getAccessControlDisabledReason(
        AccessControlResourceType.CustomerAnalytics,
        AccessControlLevel.Editor
    )
    const canEdit = !request.is_archived && !editorDisabledReason
    const addAccountDisabledReason = request.is_archived
        ? 'Restore this request before adding an account'
        : editorDisabledReason

    return (
        <div className="@container w-full max-w-[calc(160ch+5rem)] mx-auto px-6 py-5 text-sm">
            <header className="flex flex-col gap-3 mb-6 pb-5 border-b border-primary">
                <div className="flex flex-wrap items-center justify-between gap-2">
                    <LemonButton
                        type="tertiary"
                        size="small"
                        icon={<IconArrowLeft />}
                        to={featureRequestBackUrl}
                        className="-ml-2"
                        aria-label={featureRequestBackLabel ?? 'Back'}
                        tooltip={featureRequestBackLabel ? undefined : 'Back'}
                    >
                        {featureRequestBackLabel}
                    </LemonButton>
                    <div className="flex items-center gap-2">
                        {!request.is_archived && (
                            <LemonButton
                                type="secondary"
                                size="small"
                                icon={<IconPencil />}
                                onClick={() => openEditRequest(request)}
                                disabledReason={editorDisabledReason}
                                data-attr="edit-feature-request"
                            >
                                Edit
                            </LemonButton>
                        )}
                        <LemonButton
                            type="secondary"
                            size="small"
                            icon={<IconArchive />}
                            onClick={request.is_archived ? restoreActiveRequest : archiveActiveRequest}
                            loading={mutatingArchive}
                            disabledReason={editorDisabledReason}
                            data-attr={request.is_archived ? 'restore-feature-request' : 'archive-feature-request'}
                        >
                            {request.is_archived ? 'Restore' : 'Archive'}
                        </LemonButton>
                    </div>
                </div>
                <div className="flex flex-col gap-2 min-w-0">
                    <h1 className="m-0 break-words text-xl font-bold leading-tight tracking-tight">{request.title}</h1>
                    <div className="flex items-center gap-2 flex-wrap text-xs text-tertiary">
                        <FeatureRequestStatusBadge status={request.request_status} />
                        <FeatureRequestPriorityBadge priority={request.request_priority} />
                        {request.is_archived && <LemonTag type="muted">Archived</LemonTag>}
                        <span className="flex items-center gap-1">
                            <span>Created</span>
                            <TZLabel time={request.created_at} />
                        </span>
                        <span aria-hidden>·</span>
                        <span className="flex items-center gap-1">
                            <span>Last updated</span>
                            <TZLabel time={request.updated_at} />
                        </span>
                    </div>
                </div>
            </header>

            {request.is_archived && (
                <LemonBanner type="info" className="mb-5">
                    This request is archived. Restore it before editing.
                </LemonBanner>
            )}

            <div className="grid grid-cols-1 @5xl:grid-cols-[minmax(0,80ch)_minmax(22rem,1fr)] gap-5">
                <div className="flex min-w-0 flex-col gap-5">
                    <FeatureRequestDetailSection icon={<IconDocument />} title="Description">
                        {request.description ? (
                            <LemonMarkdown
                                disableImages
                                className="text-sm text-secondary leading-relaxed break-words [&>*+*]:mt-3"
                            >
                                {request.description}
                            </LemonMarkdown>
                        ) : (
                            <span className="text-secondary">No description provided.</span>
                        )}
                    </FeatureRequestDetailSection>
                    <FeatureRequestImages images={activeRequestImages} onShowEvidence={showHistoryTarget} />
                </div>

                <aside className="flex flex-col min-w-0 gap-5">
                    <FeatureRequestDetailSection icon={<IconFolder />} title="Product areas">
                        <div className="flex flex-wrap gap-1.5">
                            {request.product_areas.map((area) => (
                                <LemonTag key={area.id}>{area.name}</LemonTag>
                            ))}
                        </div>
                    </FeatureRequestDetailSection>

                    <FeatureRequestDetailSection
                        icon={<IconBuilding />}
                        title="Accounts and evidence"
                        collapsible
                        collapsed={accountsEvidenceCollapsed}
                        onCollapsedChange={setAccountsEvidenceCollapsed}
                        dataAttr="feature-request-accounts-evidence-collapse"
                        meta={
                            <span className="text-xs text-tertiary tabular-nums">
                                {activeRequestAccountLinks.length}{' '}
                                {activeRequestAccountLinks.length === 1 ? 'account' : 'accounts'} ·{' '}
                                {activeRequestEvidenceCount}{' '}
                                {activeRequestEvidenceCount === 1 ? 'evidence item' : 'evidence items'}
                            </span>
                        }
                        action={
                            <LemonButton
                                type="secondary"
                                size="xsmall"
                                icon={<IconPlus />}
                                onClick={openAddAccount}
                                disabledReason={addAccountDisabledReason}
                                data-attr="add-feature-request-account"
                            >
                                Add account
                            </LemonButton>
                        }
                    >
                        <div className="flex flex-col gap-2">
                            {visibleActiveRequestAccountLinks.map((accountLink) => (
                                <FeatureRequestAccountItem
                                    key={accountLink.id}
                                    accountLink={accountLink}
                                    canEdit={canEdit}
                                />
                            ))}
                            {activeRequestAccountLinks.length > FEATURE_REQUEST_ACCOUNT_PREVIEW_SIZE && (
                                <LemonButton
                                    type="tertiary"
                                    size="small"
                                    onClick={() => setRequestAccountsShowingAll(!requestAccountsShowingAll)}
                                    data-attr="feature-request-accounts-show-all"
                                    className="self-start"
                                >
                                    {requestAccountsShowingAll
                                        ? `Show first ${FEATURE_REQUEST_ACCOUNT_PREVIEW_SIZE} accounts`
                                        : `Show all ${activeRequestAccountLinks.length} accounts`}
                                </LemonButton>
                            )}
                        </div>
                    </FeatureRequestDetailSection>

                    <FeatureRequestHistorySection requestId={request.id} />
                </aside>
            </div>
            <FeatureRequestEditModal />
            <FeatureRequestAccountEvidenceModal />
        </div>
    )
}
