import { useValues } from 'kea'

import { LemonBanner, Link } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { destinationsLogic } from './tabs/destinationsLogic'

export function FailingDestinationsBanner({ sourceId }: { sourceId: string }): JSX.Element | null {
    const { unhealthyDestinations } = useValues(destinationsLogic({ sourceId }))

    if (unhealthyDestinations.length === 0) {
        return null
    }

    return (
        <div className="flex flex-col gap-2">
            {unhealthyDestinations.map((destination) => {
                const paused = destination.status === 'paused'
                const nameLink = (
                    <Link to={urls.warehouseDestination(destination.id)} data-attr="warehouse-destination-banner-link">
                        {destination.name}
                    </Link>
                )
                return (
                    <LemonBanner key={destination.id} type={paused ? 'error' : 'warning'}>
                        <div className="flex flex-col gap-1 min-w-0 break-words">
                            <div>
                                {paused ? (
                                    <>
                                        {nameLink}
                                        <span>
                                            {' '}
                                            is paused after repeated delivery failures. Tables that sync only to this
                                            destination are not running.
                                        </span>
                                    </>
                                ) : (
                                    <>
                                        <span>Syncs are failing to deliver to </span>
                                        {nameLink}
                                        <span>.</span>
                                    </>
                                )}
                            </div>
                            {destination.latest_error && (
                                <div className="text-xs break-words">{destination.latest_error}</div>
                            )}
                            <div>
                                {paused
                                    ? 'Open the destination and save it to resume.'
                                    : 'Open the destination to fix its settings.'}
                            </div>
                        </div>
                    </LemonBanner>
                )
            })}
        </div>
    )
}
