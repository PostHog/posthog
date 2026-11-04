import { useActions, useValues } from 'kea'

import { urls } from 'scenes/urls'

import { MigrationPrefillConfirm } from '../../shared/components/MigrationPrefillConfirm'
import { destinationConnectSceneLogic } from './destinationConnectSceneLogic'

export function DestinationMigrationPrefillConfirm({ kind }: { kind: string }): JSX.Element {
    const { migrationCreator, prefilledFieldRows, prefillConfirmed } = useValues(destinationConnectSceneLogic)
    const { setPrefillConfirmed } = useActions(destinationConnectSceneLogic)

    return (
        <MigrationPrefillConfirm
            creator={migrationCreator}
            rows={prefilledFieldRows}
            confirmed={prefillConfirmed}
            onConfirmedChange={setPrefillConfirmed}
            noun="destination"
            trustNote="PostHog sends the credentials you enter to this server, so only continue if you trust it."
            newSetupUrl={urls.warehouseDestinationConnect(kind)}
            className="mb-4"
        />
    )
}
