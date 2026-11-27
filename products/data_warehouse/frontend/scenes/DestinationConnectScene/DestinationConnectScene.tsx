import { useActions, useValues } from 'kea'

import { LemonButton, Spinner } from '@posthog/lemon-ui'

import { NotFound } from 'lib/components/NotFound'
import { FEATURE_FLAGS } from 'lib/constants'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { destinationTypeLabel } from '../../shared/components/DestinationIcon'
import { destinationConnectSceneLogic } from './destinationConnectSceneLogic'
import { DestinationMigrationPrefillConfirm } from './DestinationMigrationPrefillConfirm'

export const scene: SceneExport = {
    component: DestinationConnectScene,
    logic: destinationConnectSceneLogic,
}

export function DestinationConnectScene(): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    const {
        kind,
        destinationDefinition,
        integrationSetup,
        setupModalOpen,
        openSetupDisabledReason,
        integrationId,
        handBackStatus,
        migrationItemId,
        migrationPrefillLoading,
        setupLock,
        showPrefillConfirm,
    } = useValues(destinationConnectSceneLogic)
    const { setModalOpen, completeSetup } = useActions(destinationConnectSceneLogic)

    if (!featureFlags[FEATURE_FLAGS.WAREHOUSE_MULTI_DESTINATION]) {
        return <NotFound object="page" caption="Warehouse destinations isn't available for this project yet." />
    }

    const SetupModal = integrationSetup?.SetupModal
    if (!kind || !destinationDefinition || !SetupModal) {
        return (
            <SceneContent>
                <LemonBanner
                    type="error"
                    action={{ children: 'Open warehouse destinations', to: urls.warehouseDestinations() }}
                >
                    {kind
                        ? "This link names a connection we don't support."
                        : "This link doesn't say which connection to set up."}{' '}
                    Add the destination from warehouse destinations instead.
                </LemonBanner>
            </SceneContent>
        )
    }

    if (migrationPrefillLoading) {
        return (
            <SceneContent>
                <Spinner />
            </SceneContent>
        )
    }

    const typeLabel = destinationTypeLabel(destinationDefinition.type)

    return (
        <SceneContent>
            <SceneTitleSection
                name={`Connect ${typeLabel} destination`}
                resourceType={{ type: 'data_warehouse' }}
                description={
                    integrationId === null
                        ? `Enter your ${typeLabel} credentials. PostHog stores them encrypted and never shares them with anyone, including the assistant that sent you here.`
                        : undefined
                }
            />
            <div className="max-w-200">
                {showPrefillConfirm && <DestinationMigrationPrefillConfirm />}
                {integrationId !== null ? (
                    <LemonBanner type={handBackStatus === 'sending' ? 'info' : 'success'}>
                        <p className="font-semibold mb-1">{typeLabel} connection saved</p>
                        {handBackStatus === 'sending' ? (
                            <p className="m-0 text-sm">Sending the connection to the assistant…</p>
                        ) : handBackStatus === 'sent' ? (
                            <p className="m-0 text-sm">
                                The assistant can see this connection now. Go back to your terminal or chat to finish
                                creating the destination. You can close this tab.
                            </p>
                        ) : (
                            <p className="m-0 text-sm">
                                {handBackStatus === 'failed'
                                    ? "We couldn't send the connection to the assistant. "
                                    : ''}
                                Copy this connection id into your chat: <code>{integrationId}</code>. The assistant uses
                                it to create the destination, which doesn't exist yet. Then you can close this tab.
                            </p>
                        )}
                    </LemonBanner>
                ) : (
                    !setupModalOpen && (
                        <LemonButton
                            type="primary"
                            onClick={() => setModalOpen(true)}
                            disabledReason={openSetupDisabledReason}
                            data-attr="warehouse-destination-connect-open"
                        >
                            Enter credentials
                        </LemonButton>
                    )
                )}
            </div>
            <SetupModal
                // The form reads its locked values once, so another migration item gets a fresh form.
                key={String(migrationItemId)}
                isOpen={setupModalOpen}
                kind={kind}
                locked={setupLock}
                // The modals' close button calls onComplete with the click event, so only a number is a saved id.
                onComplete={(id) => (typeof id === 'number' ? completeSetup(id, migrationItemId) : setModalOpen(false))}
                onClose={() => setModalOpen(false)}
            />
        </SceneContent>
    )
}
