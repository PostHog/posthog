import { useActions, useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import 'lib/components/CyclotronJob/integrations/integrationSetups'
import { getIntegrationSetup } from 'lib/components/CyclotronJob/integrations/integrationSetupRegistry'
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

export const scene: SceneExport = {
    component: DestinationConnectScene,
    logic: destinationConnectSceneLogic,
}

export function DestinationConnectScene(): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    const { kind, destinationDefinition, isModalOpen, integrationId } = useValues(destinationConnectSceneLogic)
    const { setModalOpen, setIntegrationId } = useActions(destinationConnectSceneLogic)

    if (!featureFlags[FEATURE_FLAGS.WAREHOUSE_MULTI_DESTINATION]) {
        return <NotFound object="page" caption="Warehouse destinations isn't available for this project yet." />
    }

    const SetupModal = kind ? getIntegrationSetup(kind)?.SetupModal : undefined
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
                {integrationId !== null ? (
                    <LemonBanner type="success">
                        <p className="font-semibold mb-1">{typeLabel} connection saved. You can close this tab.</p>
                        <p className="m-0 text-sm">
                            The destination doesn't exist yet. Return to your chat and tell the assistant you're done,
                            and it will create the destination with this connection. Connection id:{' '}
                            <code>{integrationId}</code>.
                        </p>
                    </LemonBanner>
                ) : (
                    !isModalOpen && (
                        <LemonButton
                            type="primary"
                            onClick={() => setModalOpen(true)}
                            data-attr="warehouse-destination-connect-open"
                        >
                            Enter credentials
                        </LemonButton>
                    )
                )}
            </div>
            <SetupModal
                isOpen={isModalOpen && integrationId === null}
                kind={kind}
                onComplete={(id) => (id ? setIntegrationId(id) : setModalOpen(false))}
                onClose={() => setModalOpen(false)}
            />
        </SceneContent>
    )
}
