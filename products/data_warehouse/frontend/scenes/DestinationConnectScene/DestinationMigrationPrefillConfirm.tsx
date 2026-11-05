import { useActions, useValues } from 'kea'

import { MigrationPrefillConfirm } from '../../shared/components/MigrationPrefillConfirm'
import { destinationConnectSceneLogic } from './destinationConnectSceneLogic'

export function DestinationMigrationPrefillConfirm(): JSX.Element {
    const { migrationCreator, prefilledFieldRows, prefillConfirmed, plainSetupUrl } =
        useValues(destinationConnectSceneLogic)
    const { setPrefillConfirmed } = useActions(destinationConnectSceneLogic)

    return (
        <MigrationPrefillConfirm
            creator={migrationCreator}
            rows={prefilledFieldRows}
            confirmed={prefillConfirmed}
            onConfirmedChange={setPrefillConfirmed}
            noun="destination"
            trustNote="PostHog sends the credentials you enter to this server, so only continue if you trust it."
            newSetupUrl={plainSetupUrl}
            className="mb-4"
        />
    )
}
