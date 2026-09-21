import { useActions, useValues } from 'kea'
import { useId } from 'react'

import { IconPlus } from '@posthog/icons'
import { LemonButton, LemonMenu, Link } from '@posthog/lemon-ui'

// Side-effect import: register all integration setups
import 'lib/components/CyclotronJob/integrations/integrationSetups'
import { getIntegrationSetup } from 'lib/components/CyclotronJob/integrations/integrationSetupRegistry'
import { useIntegrationManagementRestriction } from 'lib/integrations/integrationPermissions'
import { IntegrationsList } from 'lib/integrations/IntegrationsList'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { getIntegrationNameFromKind } from 'lib/integrations/utils'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { urls } from 'scenes/urls'

import { IntegrationKind } from '~/types'

// Storage connections a batch export destination asks for and nothing else can create. They save
// credentials straight from a modal, so settings can host the whole flow. Kinds that need an OAuth
// redirect or a key file stay with the product area that owns that flow.
const CREATABLE_KINDS: IntegrationKind[] = ['aws-s3', 's3-compatible', 'azure-blob', 'aws-redshift']

// Kinds with their own settings section above this one.
const OMITTED_KINDS: IntegrationKind[] = ['slack', 'github', 'linear']

export function OtherIntegrations(): JSX.Element {
    const { newIntegrationModalKind, newIntegrationModalId } = useValues(integrationsLogic)
    const { openNewIntegrationModal, closeNewIntegrationModal } = useActions(integrationsLogic)
    const { reportIntegrationConnectClicked, reportIntegrationSetupCompleted } = useActions(eventUsageLogic)
    const managementRestriction = useIntegrationManagementRestriction()

    // Several pickers share the modal open-state, so this settings page identifies itself the same
    // way IntegrationChoice does and only renders the modal it opened.
    const modalId = useId()
    const openKind =
        newIntegrationModalId === modalId &&
        newIntegrationModalKind &&
        CREATABLE_KINDS.includes(newIntegrationModalKind)
            ? newIntegrationModalKind
            : undefined
    const SetupModal = openKind ? getIntegrationSetup(openKind)?.SetupModal : undefined

    return (
        <div className="flex flex-col gap-2">
            <div className="flex justify-end">
                <LemonMenu
                    items={CREATABLE_KINDS.map((kind) => ({
                        label: getIntegrationNameFromKind(kind),
                        disabledReason: managementRestriction ?? undefined,
                        onClick: () => {
                            reportIntegrationConnectClicked(kind, kind, 'settings')
                            openNewIntegrationModal(kind, modalId)
                        },
                    }))}
                >
                    <LemonButton type="primary" icon={<IconPlus />} data-attr="new-other-integration">
                        New connection
                    </LemonButton>
                </LemonMenu>
            </div>

            <IntegrationsList
                omitKinds={OMITTED_KINDS}
                titleText=""
                emptyState={
                    <div className="px-4 py-6 text-center text-sm text-secondary rounded border bg-surface-primary">
                        <p className="mb-1">No other integrations connected</p>
                        <p className="text-xs text-muted text-balance mb-0">
                            Use "New connection" to set up storage for a batch export. The rest connect from the product
                            area that uses them: <Link to={urls.destinations()}>pipeline destinations</Link>,{' '}
                            <Link to={urls.settings('environment-error-tracking', 'error-tracking-integrations')}>
                                error tracking
                            </Link>{' '}
                            and{' '}
                            <Link to={urls.settings('environment-marketing-analytics', 'marketing-settings')}>
                                marketing analytics
                            </Link>
                            .
                        </p>
                    </div>
                }
            />

            {SetupModal && openKind ? (
                <SetupModal
                    isOpen
                    kind={openKind}
                    onComplete={(integrationId?: number) => {
                        if (typeof integrationId === 'number') {
                            reportIntegrationSetupCompleted(openKind, 'settings')
                        }
                        closeNewIntegrationModal()
                    }}
                    onClose={closeNewIntegrationModal}
                />
            ) : null}
        </div>
    )
}
