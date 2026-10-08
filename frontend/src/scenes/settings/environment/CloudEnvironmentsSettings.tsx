import { useActions, useValues } from 'kea'

import { IconEllipsis, IconPlus } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonDialog, LemonMenu, LemonTable, LemonTag } from '@posthog/lemon-ui'

import type { SandboxEnvironmentDTOApi } from 'products/tasks/frontend/generated/api.schemas'

import { CloudEnvironmentModal } from './CloudEnvironmentModal'
import { networkAccessLabel } from './cloudEnvironmentNetworkAccess'
import { cloudEnvironmentsLogic } from './cloudEnvironmentsLogic'

export function CloudEnvironmentsSettings(): JSX.Element {
    const { environments, environmentsLoading, environmentsFailed } = useValues(cloudEnvironmentsLogic)
    const { loadEnvironments, startNewEnvironment, editEnvironment, deleteEnvironment } =
        useActions(cloudEnvironmentsLogic)

    const confirmDelete = (environment: SandboxEnvironmentDTOApi): void => {
        LemonDialog.open({
            title: `Delete "${environment.name}"?`,
            description: 'Cloud runs that use this environment fall back to full network access.',
            primaryButton: { children: 'Delete', status: 'danger', onClick: () => deleteEnvironment(environment) },
            secondaryButton: { children: 'Cancel' },
        })
    }

    return (
        <div className="flex flex-col gap-2 max-w-200">
            <div className="flex">
                <LemonButton
                    type="primary"
                    size="small"
                    icon={<IconPlus />}
                    onClick={startNewEnvironment}
                    data-attr="cloud-environment-new"
                >
                    New environment
                </LemonButton>
            </div>
            {environmentsFailed ? (
                <LemonBanner
                    type="warning"
                    action={{ children: 'Try again', onClick: loadEnvironments, loading: environmentsLoading }}
                >
                    The environments did not load.
                </LemonBanner>
            ) : (
                <LemonTable
                    size="small"
                    loading={environmentsLoading && environments === null}
                    dataSource={environments ?? []}
                    rowKey="id"
                    emptyState="No environments yet. Cloud runs have full network access until you add one."
                    columns={[
                        {
                            title: 'Name',
                            key: 'name',
                            render: (_, environment) => (
                                <div className="flex flex-wrap items-center gap-1">
                                    <span className="font-semibold">{environment.name}</span>
                                    {environment.internal ? <LemonTag size="small">Internal</LemonTag> : null}
                                </div>
                            ),
                        },
                        {
                            title: 'Used by',
                            key: 'private',
                            render: (_, environment) => (
                                <LemonTag size="small" type={environment.private ? 'muted' : 'warning'}>
                                    {environment.private ? 'Only you' : 'Everyone in this project'}
                                </LemonTag>
                            ),
                        },
                        {
                            title: 'Network access',
                            key: 'network_access_level',
                            render: (_, environment) => networkAccessLabel(environment.network_access_level),
                        },
                        {
                            title: 'Repositories',
                            key: 'repositories',
                            render: (_, environment) =>
                                environment.repositories?.length ? (
                                    <span translate="no">{environment.repositories.join(', ')}</span>
                                ) : (
                                    <span className="text-secondary">Any repository</span>
                                ),
                        },
                        {
                            title: 'Image',
                            key: 'custom_image_name',
                            render: (_, environment) =>
                                environment.custom_image_name ? (
                                    <span>{environment.custom_image_name}</span>
                                ) : (
                                    <span className="text-secondary">Default</span>
                                ),
                        },
                        {
                            key: 'actions',
                            width: 0,
                            render: (_, environment) =>
                                environment.internal ? null : (
                                    <LemonMenu
                                        items={[
                                            { label: 'Edit', onClick: () => editEnvironment(environment) },
                                            {
                                                label: 'Delete',
                                                status: 'danger',
                                                onClick: () => confirmDelete(environment),
                                            },
                                        ]}
                                    >
                                        <LemonButton
                                            size="small"
                                            icon={<IconEllipsis />}
                                            aria-label={`Actions for ${environment.name}`}
                                        />
                                    </LemonMenu>
                                ),
                        },
                    ]}
                />
            )}
            <CloudEnvironmentModal />
        </div>
    )
}
