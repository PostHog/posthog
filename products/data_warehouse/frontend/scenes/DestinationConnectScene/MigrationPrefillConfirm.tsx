import { useActions, useValues } from 'kea'
import React from 'react'

import { LemonCheckbox, Link } from '@posthog/lemon-ui'

import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { urls } from 'scenes/urls'

import { destinationConnectSceneLogic } from './destinationConnectSceneLogic'

export function MigrationPrefillConfirm({ kind }: { kind: string }): JSX.Element {
    const { migrationCreator, prefilledFieldRows, prefillConfirmed } = useValues(destinationConnectSceneLogic)
    const { setPrefillConfirmed } = useActions(destinationConnectSceneLogic)

    return (
        <LemonBanner type="warning" className="mb-4">
            <p className="font-semibold mb-1">Check where your credentials go</p>
            <p className="m-0 mb-2 text-sm">
                {migrationCreator
                    ? `${migrationCreator.first_name || migrationCreator.email} (${migrationCreator.email}) prepared this connection.`
                    : 'A migration prepared this connection.'}{' '}
                PostHog sends the credentials you enter to this server, so only continue if you trust it.
            </p>
            <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 m-0 mb-2 text-sm">
                {prefilledFieldRows.map(({ label, value }) => (
                    <React.Fragment key={label}>
                        <dt className="text-secondary">{label}</dt>
                        <dd className="m-0 font-mono break-all">{value}</dd>
                    </React.Fragment>
                ))}
            </dl>
            <div className="flex flex-wrap items-center justify-between gap-2">
                <LemonCheckbox
                    checked={prefillConfirmed}
                    onChange={setPrefillConfirmed}
                    label="I confirm this is the right server"
                    data-attr="destination-connect-confirm-prefill"
                />
                <Link
                    to={urls.warehouseDestinationConnect(kind)}
                    data-attr="destination-connect-new-destination-instead"
                >
                    Set up a new destination instead
                </Link>
            </div>
        </LemonBanner>
    )
}
