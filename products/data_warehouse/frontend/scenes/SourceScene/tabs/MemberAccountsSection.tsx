import { useActions, useValues } from 'kea'

import { IconPlus, IconTrash } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonSkeleton } from '@posthog/lemon-ui'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TeamMembershipLevel } from 'lib/constants'
import { integrationAuthorizeUrl, integrationsLogic, reconnectReturnUrl } from 'lib/integrations/integrationsLogic'
import { IntegrationView } from 'lib/integrations/IntegrationView'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { userLogic } from 'scenes/userLogic'

export interface MemberAccountsSectionProps {
    /** Integration kind that each project member connects their own account with. */
    integrationKind: string
    /** Name of the service, as the source catalog shows it. */
    sourceLabel: string
}

export function MemberAccountsSection({ integrationKind, sourceLabel }: MemberAccountsSectionProps): JSX.Element {
    const { integrations, integrationsLoading } = useValues(integrationsLogic)
    const { deleteIntegration } = useActions(integrationsLogic)
    const { reportIntegrationConnectClicked } = useActions(eventUsageLogic)
    const { user } = useValues(userLogic)
    const adminRestrictedReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })

    const accounts = integrations?.filter((integration) => integration.kind === integrationKind) ?? []
    const currentUserConnected = accounts.some((account) => account.created_by?.id === user?.id)

    return (
        <section className="flex flex-col gap-3" data-attr="source-member-accounts">
            <div className="flex flex-wrap items-start justify-between gap-2">
                <div className="max-w-160">
                    <h3 className="mb-1">Connected accounts</h3>
                    <p className="text-secondary mb-0">
                        Each teammate connects their own {sourceLabel} account, and this source syncs all of them.
                        Everyone who can query this project's data can see what your account syncs.
                    </p>
                </div>
                <LemonButton
                    type={currentUserConnected ? 'secondary' : 'primary'}
                    icon={currentUserConnected ? undefined : <IconPlus />}
                    disableClientSideRouting
                    loading={integrationsLoading}
                    to={integrationAuthorizeUrl({
                        kind: integrationKind,
                        next: reconnectReturnUrl(window.location.pathname, window.location.search),
                    })}
                    onClick={() =>
                        reportIntegrationConnectClicked(
                            integrationKind,
                            integrationKind,
                            'warehouse_source_member_accounts'
                        )
                    }
                    // pinned: autocapture and Playwright selector
                    data-attr="source-member-accounts-connect"
                >
                    {currentUserConnected ? 'Reconnect my account' : 'Add my data'}
                </LemonButton>
            </div>
            {integrations === null ? (
                integrationsLoading ? (
                    <LemonSkeleton className="h-16" />
                ) : (
                    <LemonBanner type="error">
                        Couldn't load the connected accounts. Refresh the page to try again.
                    </LemonBanner>
                )
            ) : accounts.length === 0 ? (
                <div className="rounded border border-dashed p-4 text-center text-secondary">
                    No accounts are connected yet. Add your data to start syncing.
                </div>
            ) : (
                accounts.map((account) => (
                    <IntegrationView
                        key={account.id}
                        integration={account}
                        // A custom suffix replaces the built-in Disconnect button, which only admins can use.
                        suffix={
                            <LemonButton
                                type="secondary"
                                status="danger"
                                icon={<IconTrash />}
                                onClick={() => deleteIntegration(account.id)}
                                disabledReason={
                                    account.created_by?.id === user?.id
                                        ? undefined
                                        : (adminRestrictedReason ?? undefined)
                                }
                                // pinned: autocapture and Playwright selector
                                data-attr="source-member-accounts-disconnect"
                            >
                                Disconnect
                            </LemonButton>
                        }
                    />
                ))
            )}
        </section>
    )
}
