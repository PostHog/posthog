import { useValues } from 'kea'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { useEffect } from 'react'
import { useState } from 'react'
import { teamLogic } from 'scenes/teamLogic'
import { useDestinationTypes } from './DestinationTypes'
import SkeletonImage from 'antd/lib/skeleton/Image'
import { LemonButton } from '@posthog/lemon-ui'

export const DestinationsList = (): JSX.Element => {
    // Displays a table of all destinations for the current team. The user can
    // click on the "Create" button which takes the user to the destination
    // types list page. The user can click on the "Edit" button to edit the
    // destination, and the "Delete" button to delete the destination.
    //
    // For each destination the user can see the icon for the type of
    // destination, the name of the destination, the name of the destination
    // type, and the user specified description of the destination, when the
    // destination was created and last updated.
    //
    // Further, the user should easily be able to see some high level stats for
    // the destination, including the number of events sent to the destination,
    // the number of failures in the last 24 hours, and the number of successes
    // in the last 24 hours.
    //
    // If we fail to retrieve the destinations, we display an error message
    // instead.
    //
    // For consistency with the rest of the application, we use the LemonTable
    // UI component.

    const { currentTeam } = useValues(teamLogic)

    const { destinations, loading, error } = useDestinations()
    const { destinationTypes } = useDestinationTypes()

    if (loading) {
        return <Spinner />
    }

    if (error) {
        return <div>Error: {error?.message}</div>
    }

    if (!currentTeam) {
        return <div>Team not found</div>
    }

    // Create a lookup from destination type id to destination type.
    const destinationTypesLookup = Object.fromEntries(
        destinationTypes.map((destinationType) => [destinationType.id, destinationType])
    )

    // Display a list of all destinations for the current team.

    return (
        <div>
            <h1>Destinations</h1>
            <div>
                <LemonButton onClick={() => history.pushState(undefined, '', `/destinations-types`)}>
                    Create
                </LemonButton>
            </div>
            <table className="table-auto">
                <thead>
                    <tr>
                        <th>Icon</th>
                        <th>Name</th>
                        <th>Type</th>
                        <th>Description</th>
                        <th>Created</th>
                        <th>Updated</th>
                        <th>Events Sent</th>
                        <th>Failures</th>
                        <th>Successes</th>
                        <th>Edit</th>
                        <th>Delete</th>
                    </tr>
                </thead>
                <tbody>
                    {destinations.map((destination) => {
                        const destinationType = destinationTypesLookup[destination.type]
                        return (
                            <tr key={destination.id}>
                                <td>
                                    {/* If we have a destinationType.icon_url, display the icon. Otherwise display a placeholder. */}
                                    {destinationType.icon_url ? (
                                        <img src={destinationType.icon_url} alt={destinationType.name} />
                                    ) : (
                                        <SkeletonImage />
                                    )}
                                </td>
                                <td>{destination.name}</td>
                                <td>{destinationType.name}</td>
                                <td>{destination.description}</td>
                                <td>{destination.created_at}</td>
                                <td>{destination.updated_at}</td>
                                <td>{destination.stats.events_sent_last_24_hours}</td>
                                <td>{destination.stats.failures_last_24_hours}</td>
                                <td>{destination.stats.successes_last_24_hours}</td>
                                <td>
                                    <a href={`/destinations/${destination.id}`}>Edit</a>
                                </td>
                                <td>
                                    <a href={`/destinations/${destination.id}/delete`}>Delete</a>
                                </td>
                            </tr>
                        )
                    })}
                </tbody>
            </table>
        </div>
    )
}

const useDestinations = (): { destinations: Destination[]; loading: boolean; error: Error | null } => {
    const { currentTeam } = useValues(teamLogic)

    const [destinations, setDestinations] = useState<Destination[]>([])
    const [loading, setLoading] = useState(true)
    const [error, setError] = useState<Error | null>(null)

    useEffect(() => {
        if (currentTeam) {
            setLoading(true)
            setError(null)
            const controller = new AbortController()
            fetch(`/api/projects/${currentTeam.id}/destinations/`, { signal: controller.signal })
                .then(async (response) => {
                    if (response.ok) {
                        const data = (await response.json()) as DestinationsListResponse
                        setDestinations(data.destinations)
                        setLoading(false)
                    } else {
                        setError(new Error('Failed to retrieve destinations'))
                        setLoading(false)
                    }
                })
                .catch((error) => {
                    if (error.name !== 'AbortError') {
                        setError(error)
                        setLoading(false)
                    }
                })
            return () => {
                controller.abort()
            }
        }
    }, [currentTeam])

    return { destinations, loading, error }
}

export type GenericDestinationData = {
    name: string
    type: string
    description: string

    mappings: {
        filter: {
            type: string
            value: string
        }
        transformation: {
            type: 'jsonata'
            value: string
        }
    }[]
}

export type WebhookDestination = {
    type: 'webhook'
    config: {
        url: string
        headers: {
            name: string
            value: string
        }[]
    }
} & GenericDestinationData

export type AmplitudeDestination = {
    type: 'amplitude'
    config: {
        api_key: string
    }
} & GenericDestinationData

export type OptimizelyDestination = {
    type: 'optimizely'
    config: {
        sdk_key: string
    }
} & GenericDestinationData

export type MixpanelDestination = {
    type: 'mixpanel'
    config: {
        api_secret: string
    }
} & GenericDestinationData

export type DestinationMetadata = {
    id: string

    created_at: string
    updated_at: string
}

export type DestinationStats = {
    stats: {
        events_sent_last_24_hours: number
        failures_last_24_hours: number
        successes_last_24_hours: number
    }
}

export type DestinationData = WebhookDestination | AmplitudeDestination | OptimizelyDestination | MixpanelDestination

export type Destination = DestinationData & DestinationMetadata & DestinationStats

type DestinationsListResponse = {
    destinations: Destination[]
}
