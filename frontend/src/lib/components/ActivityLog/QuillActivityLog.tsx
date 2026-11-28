import { useActions, useValues } from 'kea'

import { Empty, EmptyDescription, EmptyHeader, EmptyTitle, Skeleton, Text } from '@posthog/quill'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { QuillSurfaceContext } from 'lib/ui/QuillSurface/quillSurfaceContext'
import { userHasAccess } from 'lib/utils/accessControlUtils'
import { userLogic } from 'scenes/userLogic'

import { AccessControlLevel, AccessControlResourceType, AvailableFeature } from '~/types'

import { AccessDenied } from '../AccessDenied'
import { PayGateMini } from '../PayGateMini/PayGateMini'
import { QuillTablePagination } from '../QuillTablePagination/QuillTablePagination'
import { ActivityLogProps } from './ActivityLog'
import { activityLogLogic } from './activityLogLogic'
import { QuillActivityLogRow } from './QuillActivityLogRow'

function scopeNoun(scope: ActivityLogProps['scope']): string {
    return (Array.isArray(scope) ? scope[0] : scope)
        .replace(/([A-Z])/g, ' $1')
        .trim()
        .toLowerCase()
}

/** Quill sibling of `ActivityLog`, with the same props and logic. A caller under `today-rail-nav` picks it. */
export function QuillActivityLog({
    scope,
    id,
    caption,
    startingPage = 1,
    renderRowActions,
}: ActivityLogProps): JSX.Element | null {
    const { user } = useValues(userLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    if (!userHasAccess(AccessControlResourceType.ActivityLog, AccessControlLevel.Viewer)) {
        return <AccessDenied object="activity logs" />
    }

    return (
        <QuillSurfaceContext.Provider value={true}>
            <div className="flex flex-col gap-4" data-attr="activity-log">
                {caption && (
                    <Text size="sm" variant="muted" render={<div />} className="max-w-200">
                        {caption}
                    </Text>
                )}
                <PayGateMini
                    feature={AvailableFeature.AUDIT_LOGS}
                    featureDetail="activity-log"
                    overrideShouldShowGate={user?.is_impersonated || !!featureFlags[FEATURE_FLAGS.AUDIT_LOGS_ACCESS]}
                >
                    <QuillActivityLogContents
                        scope={scope}
                        id={id}
                        caption={caption}
                        startingPage={startingPage}
                        renderRowActions={renderRowActions}
                    />
                </PayGateMini>
            </div>
        </QuillSurfaceContext.Provider>
    )
}

function QuillActivityLogContents({
    scope,
    id,
    caption,
    startingPage = 1,
    renderRowActions,
}: ActivityLogProps): JSX.Element {
    const logic = activityLogLogic({ scope, id, caption, startingPage })
    const { humanizedActivity, activityLoading, pagination, highlightedActivityId } = useValues(logic)
    const { setPage } = useActions(logic)

    if (activityLoading && humanizedActivity.length === 0) {
        return (
            <div className="flex flex-col gap-2" aria-label="Loading history">
                {Array.from({ length: 4 }, (_, index) => (
                    <Skeleton key={index} className="h-14" />
                ))}
            </div>
        )
    }

    if (humanizedActivity.length === 0) {
        return (
            <Empty data-attr="product-introduction-history record">
                <EmptyHeader>
                    <EmptyTitle>No history records yet</EmptyTitle>
                    <EmptyDescription>
                        {`History shows any ${scopeNoun(scope)} changes that have been made. After making changes you'll see them logged here.`}
                    </EmptyDescription>
                </EmptyHeader>
            </Empty>
        )
    }

    const total = pagination.entryCount ?? humanizedActivity.length
    const pageSize = pagination.pageSize ?? humanizedActivity.length

    return (
        <div className="flex flex-col gap-2">
            <div className="flex flex-col gap-1">
                {humanizedActivity.map((logItem, index) => (
                    <QuillActivityLogRow
                        key={logItem.id || index}
                        logItem={logItem}
                        highlighted={logItem.id === highlightedActivityId}
                        actions={renderRowActions?.(logItem)}
                    />
                ))}
            </div>
            {total > pageSize && (
                <QuillTablePagination
                    currentPage={pagination.currentPage ?? 1}
                    pageCount={Math.ceil(total / pageSize)}
                    pageSize={pageSize}
                    total={total}
                    onPageChange={setPage}
                />
            )}
        </div>
    )
}
