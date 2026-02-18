import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { IconCopy, IconEllipsis, IconKey, IconPlus, IconTrash } from '@posthog/icons'
import {
    LemonBanner,
    LemonButton,
    LemonDialog,
    LemonInput,
    LemonMenu,
    LemonModal,
    LemonSkeleton,
    LemonTable,
    LemonTag,
    Tooltip,
} from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'
import { humanFriendlyDetailedTime } from 'lib/utils'

import { OAuthApplicationType } from '~/types'

import { oauthAppsLogic } from './oauthAppsLogic'

function OAuthAppModal(): JSX.Element {
    const {
        editingAppId,
        isNewApp,
        oauthAppFormChanged,
        isOauthAppFormSubmitting,
        oauthAppForm,
        newRedirectUri,
        newlyCreatedApp,
    } = useValues(oauthAppsLogic)
    const {
        setEditingAppId,
        setNewRedirectUri,
        addRedirectUri,
        removeRedirectUri,
        submitOauthAppForm,
        copyToClipboard,
    } = useActions(oauthAppsLogic)

    const showCredentialsView = newlyCreatedApp !== null

    return (
        <LemonModal
            title={
                showCredentialsView
                    ? 'Application created'
                    : isNewApp
                      ? 'Create OAuth application'
                      : 'Edit OAuth application'
            }
            onClose={() => setEditingAppId(null)}
            isOpen={!!editingAppId || showCredentialsView}
            width="36rem"
            hasUnsavedInput={!showCredentialsView && oauthAppFormChanged}
            footer={
                showCredentialsView ? (
                    <LemonButton type="primary" onClick={() => setEditingAppId(null)}>
                        Done
                    </LemonButton>
                ) : (
                    <>
                        <LemonButton type="secondary" onClick={() => setEditingAppId(null)}>
                            Cancel
                        </LemonButton>
                        <LemonButton
                            type="primary"
                            loading={isOauthAppFormSubmitting}
                            disabled={!oauthAppFormChanged}
                            onClick={() => submitOauthAppForm()}
                        >
                            {isNewApp ? 'Create application' : 'Save changes'}
                        </LemonButton>
                    </>
                )
            }
        >
            {showCredentialsView ? (
                <div className="space-y-4">
                    <LemonBanner type="warning">
                        <strong>Save your client secret now!</strong> You won't be able to see it again after closing
                        this dialog.
                    </LemonBanner>

                    <div className="space-y-3">
                        <div>
                            <label className="text-xs font-semibold uppercase text-secondary mb-1 block">
                                Client ID
                            </label>
                            <div className="flex items-center gap-2">
                                <code className="flex-1 bg-fill-primary rounded p-2 text-sm font-mono break-all">
                                    {newlyCreatedApp.client_id}
                                </code>
                                <LemonButton
                                    icon={<IconCopy />}
                                    size="small"
                                    onClick={() => copyToClipboard(newlyCreatedApp.client_id, 'Client ID')}
                                />
                            </div>
                        </div>

                        <div>
                            <label className="text-xs font-semibold uppercase text-secondary mb-1 block">
                                Client secret
                            </label>
                            <div className="flex items-center gap-2">
                                <code className="flex-1 bg-fill-primary rounded p-2 text-sm font-mono break-all">
                                    {newlyCreatedApp.client_secret}
                                </code>
                                <LemonButton
                                    icon={<IconCopy />}
                                    size="small"
                                    onClick={() =>
                                        copyToClipboard(newlyCreatedApp.client_secret || '', 'Client secret')
                                    }
                                />
                            </div>
                        </div>
                    </div>
                </div>
            ) : (
                <Form logic={oauthAppsLogic} formKey="oauthAppForm" className="space-y-4">
                    <LemonField name="name" label="Application name">
                        <LemonInput placeholder="My Integration" maxLength={255} />
                    </LemonField>

                    <LemonField
                        name="redirect_uris_list"
                        label="Redirect URIs"
                        info="URLs that users will be redirected to after authorization. Use HTTPS for production."
                    >
                        {() => (
                            <div className="space-y-2">
                                {oauthAppForm.redirect_uris_list.map((uri, index) => (
                                    <div key={index} className="flex items-center gap-2">
                                        <code className="flex-1 bg-fill-primary rounded p-2 text-sm break-all">
                                            {uri}
                                        </code>
                                        <LemonButton
                                            icon={<IconTrash />}
                                            size="small"
                                            status="danger"
                                            onClick={() => removeRedirectUri(index)}
                                        />
                                    </div>
                                ))}
                                <div className="flex items-center gap-2">
                                    <LemonInput
                                        value={newRedirectUri}
                                        onChange={(val) => setNewRedirectUri(val)}
                                        placeholder="https://your-app.com/callback"
                                        className="flex-1"
                                        onPressEnter={() => {
                                            addRedirectUri()
                                        }}
                                    />
                                    <LemonButton
                                        icon={<IconPlus />}
                                        size="small"
                                        type="secondary"
                                        onClick={() => addRedirectUri()}
                                        disabledReason={!newRedirectUri.trim() ? 'Enter a URI first' : undefined}
                                    >
                                        Add
                                    </LemonButton>
                                </div>
                            </div>
                        )}
                    </LemonField>
                </Form>
            )}
        </LemonModal>
    )
}

function OAuthAppsTable(): JSX.Element {
    const { oauthApps, oauthAppsLoading } = useValues(oauthAppsLogic)
    const { setEditingAppId, deleteOAuthApp, rotateSecret, copyToClipboard } = useActions(oauthAppsLogic)

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
                <h3 className="text-base font-semibold mb-1">No OAuth applications</h3>
                <p className="text-secondary mb-4">
                    Create an OAuth application to allow third-party services to authenticate with PostHog.
                </p>
                <LemonButton type="primary" icon={<IconPlus />} onClick={() => setEditingAppId('new')}>
                    Create application
                </LemonButton>
            </div>
        )
    }

    return (
        <LemonTable
            dataSource={oauthApps}
            className="mt-4"
            columns={[
                {
                    title: 'Name',
                    key: 'name',
                    render: (_, app: OAuthApplicationType) => (
                        <div className="flex items-center gap-2">
                            <span className="font-semibold">{app.name}</span>
                            {app.is_verified && (
                                <LemonTag type="success" size="small">
                                    Verified
                                </LemonTag>
                            )}
                            {app.is_first_party && (
                                <LemonTag type="highlight" size="small">
                                    First party
                                </LemonTag>
                            )}
                            {app.is_dcr_client && (
                                <LemonTag type="muted" size="small">
                                    DCR
                                </LemonTag>
                            )}
                        </div>
                    ),
                },
                {
                    title: 'Client ID',
                    key: 'client_id',
                    render: (_, app: OAuthApplicationType) => (
                        <div className="flex items-center gap-1">
                            <code className="text-xs bg-fill-primary rounded px-1.5 py-0.5 font-mono truncate max-w-[200px]">
                                {app.client_id}
                            </code>
                            <Tooltip title="Copy client ID">
                                <LemonButton
                                    icon={<IconCopy />}
                                    size="xsmall"
                                    noPadding
                                    onClick={() => copyToClipboard(app.client_id, 'Client ID')}
                                />
                            </Tooltip>
                        </div>
                    ),
                },
                {
                    title: 'Redirect URIs',
                    key: 'redirect_uris',
                    render: (_, app: OAuthApplicationType) => {
                        const uris = app.redirect_uris_list || []
                        if (uris.length === 0) {
                            return <span className="text-muted">None</span>
                        }
                        if (uris.length === 1) {
                            return (
                                <code className="text-xs bg-fill-primary rounded px-1.5 py-0.5 truncate max-w-[200px] inline-block">
                                    {uris[0]}
                                </code>
                            )
                        }
                        return (
                            <Tooltip title={uris.join('\n')}>
                                <span className="text-muted cursor-help">{uris.length} URIs</span>
                            </Tooltip>
                        )
                    },
                },
                {
                    title: 'Created',
                    key: 'created_at',
                    render: (_, app: OAuthApplicationType) => (
                        <span className="text-muted text-sm">{humanFriendlyDetailedTime(app.created_at)}</span>
                    ),
                },
                {
                    title: '',
                    key: 'actions',
                    width: 0,
                    render: (_, app: OAuthApplicationType) => (
                        <LemonMenu
                            items={[
                                {
                                    label: 'Edit',
                                    onClick: () => setEditingAppId(app.id),
                                },
                                {
                                    label: 'Rotate secret',
                                    onClick: () => {
                                        LemonDialog.open({
                                            title: 'Rotate client secret?',
                                            description:
                                                'This will immediately invalidate the current client secret. Any applications using the old secret will stop working.',
                                            primaryButton: {
                                                status: 'danger',
                                                children: 'Rotate secret',
                                                onClick: () => rotateSecret(app.id),
                                            },
                                            secondaryButton: {
                                                children: 'Cancel',
                                            },
                                        })
                                    },
                                },
                                {
                                    label: 'Delete',
                                    status: 'danger',
                                    onClick: () => {
                                        LemonDialog.open({
                                            title: `Delete "${app.name}"?`,
                                            description:
                                                'This action cannot be undone. Any integrations using this application will stop working immediately.',
                                            primaryButton: {
                                                status: 'danger',
                                                children: 'Delete',
                                                onClick: () => deleteOAuthApp(app.id),
                                            },
                                            secondaryButton: {
                                                children: 'Cancel',
                                            },
                                        })
                                    },
                                },
                            ]}
                        >
                            <LemonButton icon={<IconEllipsis />} size="small" />
                        </LemonMenu>
                    ),
                },
            ]}
        />
    )
}

function RotatedSecretBanner(): JSX.Element | null {
    const { rotatedSecret } = useValues(oauthAppsLogic)
    const { copyToClipboard } = useActions(oauthAppsLogic)

    if (!rotatedSecret) {
        return null
    }

    return (
        <LemonBanner type="warning" className="mt-4">
            <div className="flex items-center justify-between gap-4">
                <div>
                    <strong>New client secret generated!</strong> Copy it now - you won't be able to see it again.
                </div>
                <div className="flex items-center gap-2">
                    <code className="bg-fill-primary rounded px-2 py-1 text-sm font-mono">{rotatedSecret}</code>
                    <LemonButton
                        icon={<IconCopy />}
                        size="small"
                        onClick={() => copyToClipboard(rotatedSecret, 'Client secret')}
                    />
                </div>
            </div>
        </LemonBanner>
    )
}

export function OAuthApps(): JSX.Element {
    const { oauthApps } = useValues(oauthAppsLogic)
    const { setEditingAppId } = useActions(oauthAppsLogic)

    return (
        <div>
            {oauthApps.length > 0 && (
                <LemonButton type="primary" icon={<IconPlus />} onClick={() => setEditingAppId('new')}>
                    Create OAuth application
                </LemonButton>
            )}

            <RotatedSecretBanner />
            <OAuthAppsTable />
            <OAuthAppModal />
        </div>
    )
}
