import { useActions, useValues } from 'kea'

import { LemonButton, LemonDialog, LemonTable, LemonTag } from '@posthog/lemon-ui'

import { humanFriendlyDetailedTime } from 'lib/utils'

import { connectedAppsLogic, ConnectedApp } from './connectedAppsLogic'

export function ConnectedApps(): JSX.Element {
    const { connectedApps, connectedAppsLoading } = useValues(connectedAppsLogic)
    const { revokeApp } = useActions(connectedAppsLogic)

    const handleRevoke = (app: ConnectedApp): void => {
        LemonDialog.open({
            title: `Revoke access for ${app.name}?`,
            description: `This will revoke all tokens and permissions granted to ${app.name}. The app will no longer be able to access your PostHog account. You can re-authorize it at any time through the application's own interface.`,
            primaryButton: {
                children: 'Revoke',
                status: 'danger',
                onClick: () => revokeApp(app.id),
            },
            secondaryButton: {
                children: 'Cancel',
            },
        })
    }

    return (
        <LemonTable
            dataSource={connectedApps}
            loading={connectedAppsLoading}
            columns={[
                {
                    title: 'Application',
                    dataIndex: 'name',
                    render: (_, app) => (
                        <div className="flex items-center gap-2">
                            {app.logo_uri ? (
                                <div className="w-8 h-8 shrink-0 rounded bg-bg-light border flex items-center justify-center p-1">
                                    <img
                                        src={app.logo_uri}
                                        alt={`${app.name} logo`}
                                        className="w-full h-full object-contain"
                                    />
                                </div>
                            ) : (
                                <div className="w-8 h-8 shrink-0 rounded bg-border flex items-center justify-center text-sm font-bold text-muted">
                                    {app.name.charAt(0).toUpperCase()}
                                </div>
                            )}
                            <span className="font-medium">{app.name}</span>
                            {app.is_first_party ? (
                                <LemonTag type="highlight" size="small">
                                    PostHog
                                </LemonTag>
                            ) : app.is_verified ? (
                                <LemonTag type="success" size="small">
                                    Verified
                                </LemonTag>
                            ) : null}
                        </div>
                    ),
                },
                {
                    title: 'Scopes',
                    dataIndex: 'scopes',
                    render: (_, app) =>
                        app.scopes.length > 0 ? (
                            <div className="flex flex-wrap gap-1">
                                {app.scopes.map((scope) => (
                                    <LemonTag key={scope} size="small">
                                        {scope}
                                    </LemonTag>
                                ))}
                            </div>
                        ) : (
                            <span className="text-muted">No scopes</span>
                        ),
                },
                {
                    title: 'Authorized',
                    dataIndex: 'authorized_at',
                    render: (_, app) => humanFriendlyDetailedTime(app.authorized_at),
                },
                {
                    title: '',
                    render: (_, app) => (
                        <LemonButton type="secondary" status="danger" size="small" onClick={() => handleRevoke(app)}>
                            Revoke
                        </LemonButton>
                    ),
                },
            ]}
            emptyState="No connected applications"
        />
    )
}
