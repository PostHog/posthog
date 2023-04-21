//
// A react component that allows the user to create an event destination of the
// specified type. The user can specify the name of the destination, and the
// destination's configuration. Each destination has a different configuration,
// with valid configuration specifed by the configSchema property of the
// specification.

import { Spinner } from 'lib/lemon-ui/Spinner'
import { DestinationType } from './DestinationTypes'
import { useEffect } from 'react'
import { useState } from 'react'
import { teamLogic } from 'scenes/teamLogic'
import { useValues } from 'kea'

export const CreateDestinationOfType = (): JSX.Element => {
    // Displays a form to allow the user to create a destination of the specified
    // type. The user can specify the name of the destination, and the destination's
    // configuration. Each destination has a different configuration, with valid
    // configuration specifed by the configSchema property of the specification.
    //
    // The user can click on the "Create" button to create the destination, and
    // then be taken to the destination page. If the user clicks on the "Cancel"
    // button, they are taken to the destination list page.
    //
    // If we fail to retrieve the destination type, we display an error message
    // instead.

    const { destinationType, loading, error } = useDestinationType('amplitude')

    if (loading) {
        return <Spinner />
    }

    if (error) {
        return <div>Error: {error.message}</div>
    }

    if (!destinationType) {
        return <div>Destination type not found</div>
    }

    // Display a summary of the destination type, including the name,
    // description, and icon. The icon url can we of any size, so we use the
    // object-fit property to ensure the icon is displayed in the correct
    // aspect ratio.
    //
    // By default the no events are sent to the destination. Rather the user
    // needs to specify which events they want to send to the destination, and a
    // how they want the event to be transformed before being sent to the
    // destination. We only support transformaing events to JSON for now.
    //
    // We also display a form to allow the user to specify the name of the
    // new destination, and the destination's configuration. The
    // configuration is specified by the config_schema property of the
    // destination type. The config_schema is a JSON schema, which we use to
    // generate a form. The user can then fill in the form to specify the
    // configuration.
    //
    // The user can click on the "Create" button to create the destination,
    // and then be taken to the destination list page. If the user clicks on
    // the "Cancel" button, they are taken to the destination types list
    // page.
    return (
        <>
            <div className="flex items-center">
                <div className="flex-shrink-0">
                    <img className="h-12 w-12 rounded-full object-cover" src={destinationType.icon_url} alt="" />
                </div>
                <div className="ml-4">
                    <h1 className="text-2xl font-bold text-gray-900">{destinationType.name}</h1>
                    <p className="text-gray-500">{destinationType.description}</p>
                </div>
            </div>
            <div className="mt-8">
                <form>
                    <div className="mb-4">
                        <label className="block text-gray-700 text-sm font-bold mb-2">Destination name</label>
                        <input
                            className="shadow appearance-none border rounded w-full py-2 px-3 text-gray-700 leading-tight focus:outline-none focus:shadow-outline"
                            type="text"
                            placeholder="Destination name"
                        />
                    </div>
                    <div className="mb-4">
                        <label className="block text-gray-700 text-sm font-bold mb-2">Destination configuration</label>
                    </div>
                </form>
            </div>
        </>
    )
}

const useDestinationType = (
    type: string
): { destinationType: DestinationType | undefined; loading: boolean; error: Error | null } => {
    // Use browers fetch make an http get request to
    // /api/projects/:project_id/destination-types/:type
    // Return state data, error and loading

    const [destinationType, setDestinationType] = useState<DestinationType | undefined>(undefined)
    const [loading, setLoading] = useState(true)
    const [error, setError] = useState<Error | null>(null)
    const { currentTeam } = useValues(teamLogic)

    useEffect(() => {
        if (currentTeam) {
            fetch(`/api/projects/${currentTeam.id}/destination-types/${type}`)
                .then(async (response) => {
                    if (response.ok) {
                        const data = (await response.json()) as DestinationType
                        setDestinationType(data)
                        setLoading(false)
                    } else {
                        setError(new Error('Failed to retrieve destination type'))
                        setLoading(false)
                    }
                })
                .catch((error) => {
                    setError(error)
                    setLoading(false)
                })
        }
    }, [currentTeam, type])

    return { destinationType, loading, error }
}
