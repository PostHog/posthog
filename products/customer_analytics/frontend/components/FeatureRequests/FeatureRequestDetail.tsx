import { useActions, useValues } from 'kea'
import { combineUrl } from 'kea-router'

import { IconArchive, IconArrowLeft, IconBuilding, IconDocument, IconFolder, IconPencil } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonTag, Link } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'
import { urls } from 'scenes/urls'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import type { FeatureRequestApi } from '../../generated/api.schemas'
import { FeatureRequestDetailSection } from './FeatureRequestDetailSection'
import { FeatureRequestEditModal } from './FeatureRequestEditModal'
import { FeatureRequestHistorySection } from './FeatureRequestHistorySection'
import { FeatureRequestPriorityBadge } from './FeatureRequestPriorityBadge'
import { featureRequestsLogic } from './featureRequestsLogic'
import { FeatureRequestStatusBadge } from './FeatureRequestStatusBadge'

export function FeatureRequestDetail({ request }: { request: FeatureRequestApi }): JSX.Element {
    const { mutatingArchive, listSearchParams } = useValues(featureRequestsLogic)
    const { openEditRequest, archiveActiveRequest, restoreActiveRequest } = useActions(featureRequestsLogic)
    const editorDisabledReason = getAccessControlDisabledReason(
        AccessControlResourceType.CustomerAnalytics,
        AccessControlLevel.Editor
    )

    return (
        <div className="@container w-full max-w-[calc(160ch+5rem)] mx-auto px-6 py-5 text-sm">
            <header className="flex flex-col gap-3 mb-6 pb-5 border-b border-primary">
                <div className="flex flex-wrap items-center justify-between gap-2">
                    <LemonButton
                        type="tertiary"
                        size="small"
                        icon={<IconArrowLeft />}
                        to={combineUrl(urls.customerAnalyticsFeatureRequests(), listSearchParams).url}
                        className="-ml-2"
                    >
                        Feature requests
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
                <div className="min-w-0">
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
                </div>

                <aside className="flex flex-col min-w-0 gap-5">
                    <FeatureRequestDetailSection icon={<IconBuilding />} title="Account">
                        <Link
                            to={urls.customerAnalyticsAccount(request.account.id)}
                            className="flex items-center gap-3 rounded border border-primary bg-surface-primary px-3 py-2.5 text-default hover:text-primary"
                        >
                            <span className="flex size-8 shrink-0 items-center justify-center rounded bg-fill-highlight-50 text-secondary">
                                <IconBuilding className="size-4" />
                            </span>
                            <span className="truncate font-medium">{request.account.name}</span>
                        </Link>
                    </FeatureRequestDetailSection>

                    <FeatureRequestDetailSection icon={<IconFolder />} title="Product areas">
                        <div className="flex flex-wrap gap-1.5">
                            {request.product_areas.map((area) => (
                                <LemonTag key={area.id}>{area.name}</LemonTag>
                            ))}
                        </div>
                    </FeatureRequestDetailSection>

                    <FeatureRequestHistorySection requestId={request.id} />
                </aside>
            </div>
            <FeatureRequestEditModal />
        </div>
    )
}
