import { decode } from 'he'
import { useActions, useValues } from 'kea'

import { IconCopy } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonSkeleton, LemonTable, LemonTag } from '@posthog/lemon-ui'

import { IconKey } from 'lib/lemon-ui/icons'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { humanFriendlyDetailedTime } from 'lib/utils/datetime'

import { OrganizationOAuthApplicationApi } from '~/generated/core/api.schemas'

import { OAuthAppDetails } from './OAuthAppDetails'
import { PROVISIONING_STATUS_LABELS, PROVISIONING_STATUS_TAG_TYPES } from './oauthAppProvisioningStatus'
import { oauthAppsLogic } from './oauthAppsLogic'

export function OAuthApps(): JSX.Element {
    const { oauthApps, oauthAppsLoading, oauthAppsLoadFailed } = useValues(oauthAppsLogic)
    const { loadOAuthApps } = useActions(oauthAppsLogic)

    if (oauthAppsLoadFailed && !oauthAppsLoading) {
        return (
            <LemonBanner
                type="error"
                className="mt-4"
                action={{ children: 'Try again', onClick: loadOAuthApps, 'data-attr': 'oauth-apps-retry' }}
            >
                Couldn't load your OAuth applications. Try again, and if it keeps happening contact support.
            </LemonBanner>
        )
    }

    if (oauthApps === null || (oauthAppsLoading && oauthApps.length === 0)) {
        return (
            <div className="space-y-2 mt-4">
                <LemonSkeleton className="h-12" />
                <LemonSkeleton className="h-12" />
            </div>
        )
    }

    if (oauthApps.length === 0) {
        return (
            <div className="border border-dashed rounded-lg p-8 text-center mt-4">
                <IconKey className="text-4xl text-secondary mx-auto mb-3" />
                <h3 className="text-base font-semibold mb-1">No connected applications</h3>
                <p className="text-secondary">
                    Applications will appear here when third-party tools connect to your organization.
                </p>
            </div>
        )
    }

    return (
        <LemonTable
            dataSource={oauthApps}
            className="mt-4"
            expandable={{
                expandedRowRender: (app: OrganizationOAuthApplicationApi) => <OAuthAppDetails app={app} />,
            }}
            columns={[
                {
                    title: 'Application',
                    key: 'name',
                    render: (_, app: OrganizationOAuthApplicationApi) => (
                        <div className="flex items-center gap-2">
                            <span className="font-semibold">{decode(app.name ?? '')}</span>
                            {app.is_verified && (
                                <LemonTag type="success" size="small">
                                    Verified
                                </LemonTag>
                            )}
                        </div>
                    ),
                },
                {
                    title: 'Client ID',
                    key: 'client_id',
                    render: (_, app: OrganizationOAuthApplicationApi) => (
                        <div className="flex items-center gap-1">
                            <code className="text-xs bg-fill-primary rounded px-1.5 py-0.5 font-mono truncate max-w-[200px]">
                                {app.client_id}
                            </code>
                            <LemonButton
                                icon={<IconCopy />}
                                size="xsmall"
                                noPadding
                                tooltip="Copy client ID"
                                onClick={() => void copyToClipboard(app.client_id ?? '', 'client ID')}
                            />
                        </div>
                    ),
                },
                {
                    title: 'Provisioning',
                    key: 'provisioning_status',
                    render: (_, app: OrganizationOAuthApplicationApi) =>
                        app.provisioning_status === 'not_a_partner' ? (
                            <span className="text-muted">-</span>
                        ) : (
                            <LemonTag type={PROVISIONING_STATUS_TAG_TYPES[app.provisioning_status]}>
                                {PROVISIONING_STATUS_LABELS[app.provisioning_status]}
                            </LemonTag>
                        ),
                },
                {
                    title: 'Connected',
                    key: 'created',
                    render: (_, app: OrganizationOAuthApplicationApi) => (
                        <span className="text-muted text-sm">{humanFriendlyDetailedTime(app.created)}</span>
                    ),
                },
            ]}
        />
    )
}
