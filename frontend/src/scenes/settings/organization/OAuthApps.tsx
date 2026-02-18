import { useValues } from 'kea'

import { IconCopy } from '@posthog/icons'
import { LemonButton, LemonSkeleton, LemonTable, LemonTag } from '@posthog/lemon-ui'

import { IconKey } from 'lib/lemon-ui/icons'
import { humanFriendlyDetailedTime } from 'lib/utils'
import { copyToClipboard } from 'lib/utils/copyToClipboard'

import { OrganizationOAuthApplicationApi } from '~/generated/core/api.schemas'

import { oauthAppsLogic } from './oauthAppsLogic'

export function OAuthApps(): JSX.Element {
    const { oauthApps, oauthAppsLoading } = useValues(oauthAppsLogic)

    if (oauthAppsLoading && oauthApps.length === 0) {
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
            columns={[
                {
                    title: 'Application',
                    key: 'name',
                    render: (_, app: OrganizationOAuthApplicationApi) => (
                        <div className="flex items-center gap-2">
                            <span className="font-semibold">{app.name}</span>
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
                                onClick={() => void copyToClipboard(app.client_id, 'client ID')}
                            />
                        </div>
                    ),
                },
                {
                    title: 'Redirect URIs',
                    key: 'redirect_uris',
                    render: (_, app: OrganizationOAuthApplicationApi) => {
                        const uris = app.redirect_uris_list || []
                        if (uris.length === 0) {
                            return <span className="text-muted">None</span>
                        }
                        return (
                            <div className="flex flex-col gap-0.5">
                                {uris.map((uri, i) => (
                                    <div key={i} className="flex items-center gap-1">
                                        <code className="text-xs bg-fill-primary rounded px-1.5 py-0.5 truncate max-w-[250px] block">
                                            {uri}
                                        </code>
                                        <LemonButton
                                            icon={<IconCopy />}
                                            size="xsmall"
                                            noPadding
                                            tooltip="Copy URI"
                                            onClick={() => void copyToClipboard(uri, 'redirect URI')}
                                        />
                                    </div>
                                ))}
                            </div>
                        )
                    },
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
