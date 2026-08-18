import { useActions } from 'kea'

import { IconCheck, IconEllipsis, IconInfo, IconWarning, IconX } from '@posthog/icons'
import { LemonButton, LemonMenu, LemonSkeleton, LemonTag } from '@posthog/lemon-ui'

import { Link } from 'lib/lemon-ui/Link'
import { isExternalLink } from 'lib/utils/url'

import { HealthCheck, HealthCheckStatus } from '../healthCheckTypes'
import { webAnalyticsHealthLogic } from '../webAnalyticsHealthLogic'

interface HealthCheckItemProps {
    check: HealthCheck
}

export function HealthCheckItem({ check }: HealthCheckItemProps): JSX.Element {
    const { trackActionClicked, setIssueDismissed } = useActions(webAnalyticsHealthLogic)
    const issueId = check.issueId

    const handleActionClick = (): void => {
        trackActionClicked(check.id, check.category, check.status, check.urgent ?? false)
        check.action?.onClick?.()
    }

    return (
        <div
            className={`flex items-start gap-3 p-3 rounded border border-primary/10 bg-surface-primary ${
                check.dismissed ? 'opacity-60' : ''
            }`}
        >
            <StatusIcon status={check.status} urgent={check.urgent} />
            <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                    {check.title.startsWith('$') ? (
                        <code className="font-medium text-sm bg-fill-primary px-1.5 py-0.5 rounded">{check.title}</code>
                    ) : (
                        <span className="font-medium">{check.title}</span>
                    )}
                    {check.dismissed && <LemonTag type="muted">Dismissed</LemonTag>}
                    {check.docsUrl && (
                        <Link to={check.docsUrl} target="_blank" className="text-xs text-muted">
                            Docs
                        </Link>
                    )}
                </div>
                <div className="text-sm text-secondary mt-0.5">
                    {check.status === 'loading' ? <LemonSkeleton className="w-32 h-4" /> : check.description}
                </div>
            </div>
            {check.action && !check.dismissed && (
                <div className="flex-shrink-0">
                    {check.action.to ? (
                        <LemonButton
                            type="secondary"
                            size="small"
                            to={check.action.to}
                            // External docs links must open in a new tab — navigating in place tears
                            // down the app (and ends any active session recording).
                            targetBlank={isExternalLink(check.action.to)}
                            onClick={handleActionClick}
                        >
                            {check.action.label}
                        </LemonButton>
                    ) : check.action.onClick ? (
                        <LemonButton type="secondary" size="small" onClick={handleActionClick}>
                            {check.action.label}
                        </LemonButton>
                    ) : null}
                </div>
            )}
            {issueId && (
                <div className="flex-shrink-0">
                    <LemonMenu
                        items={[
                            check.dismissed
                                ? { label: 'Restore', onClick: () => setIssueDismissed(issueId, false) }
                                : { label: 'Dismiss', onClick: () => setIssueDismissed(issueId, true) },
                        ]}
                    >
                        <LemonButton
                            type="tertiary"
                            size="small"
                            icon={<IconEllipsis />}
                            aria-label="Issue options"
                            data-attr="web-analytics-health-issue-menu"
                        />
                    </LemonMenu>
                </div>
            )}
        </div>
    )
}

function StatusIcon({ status, urgent }: { status: HealthCheckStatus; urgent?: boolean }): JSX.Element {
    const isUrgentAndFailing = urgent && status !== 'success' && status !== 'loading'

    if (isUrgentAndFailing) {
        return (
            <div className="w-6 h-6 rounded-full bg-danger flex items-center justify-center flex-shrink-0">
                <span className="text-white text-xs font-bold">!</span>
            </div>
        )
    }

    switch (status) {
        case 'success':
            return (
                <div className="w-6 h-6 rounded-full bg-success-highlight flex items-center justify-center flex-shrink-0">
                    <IconCheck className="text-success w-4 h-4" />
                </div>
            )
        case 'info':
            return (
                <div className="w-6 h-6 rounded-full bg-fill-info-secondary flex items-center justify-center flex-shrink-0">
                    <IconInfo className="text-info w-4 h-4" />
                </div>
            )
        case 'warning':
            return (
                <div className="w-6 h-6 rounded-full bg-warning-highlight flex items-center justify-center flex-shrink-0">
                    <IconWarning className="text-warning w-4 h-4" />
                </div>
            )
        case 'error':
            return (
                <div className="w-6 h-6 rounded-full bg-danger-highlight flex items-center justify-center flex-shrink-0">
                    <IconX className="text-danger w-4 h-4" />
                </div>
            )
        case 'loading':
            return (
                <div className="w-6 h-6 rounded-full bg-muted-alt flex items-center justify-center flex-shrink-0">
                    <LemonSkeleton className="w-4 h-4 rounded-full" />
                </div>
            )
    }
}
