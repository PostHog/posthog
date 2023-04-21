import SkeletonImage from 'antd/lib/skeleton/Image'
import { useValues } from 'kea'
import { PageHeader } from 'lib/components/PageHeader'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { useEffect } from 'react'
import { useState } from 'react'
import { teamLogic } from 'scenes/teamLogic'

export const DestinationTypes = (): JSX.Element => {
    // Displays the available destination types for the user, and the current
    // project_id. We user the /api/projects/<project_id>/destination_types
    // endpoint to first retrieve the available destination types whilst showing
    // a loading spinner, then once the data is available, we display the
    // destination types, including the destination type's name, short description,
    // and the associated icon. Initially we only have a webhook so the image is
    // an icon of a webhook.
    //
    // We arrange the destination types in a grid layout, with the destination
    // type name and description below the icon. The destination type name is
    // displayed in bold, and the description is displayed in a smaller font.
    // The icon url can we of any size, so we use the object-fit property to
    // ensure the icon is displayed in the correct aspect ratio. We only ever
    // have 3 destination type in a row.
    //
    // The user can click on the destination type to be taken to the destination
    // creation page, where they can create a destination of that type, which also
    // includes documentation on the destination type.
    //
    // If we fail to retrieve the destination types, we display an error message
    // instead.

    const { destinationTypes, loading, error } = useDestinationTypes()

    if (loading) {
        return <Spinner />
    }

    if (error) {
        return <div>Error: {error.message}</div>
    }

    return (
        <>
            <PageHeader title="Destinations" caption="Connect your data to your favorite tools." />
            <div className="flex flex-row space-y-2 space-x-2 items-stretch">
                {destinationTypes.map((destinationType) => (
                    <a
                        key={destinationType.id}
                        onClick={() => history.pushState(undefined, '', `/destination-types/${destinationType.id}/new`)}
                        className="w-1/3 border rounded text-left flex flex-row p-2.5 block items-center"
                    >
                        {destinationType.icon_url ? (
                            <img
                                src={destinationType.icon_url}
                                alt={destinationType.name}
                                className="object-contain w-1/6 mr-2.5"
                            />
                        ) : (
                            <SkeletonImage className="w-1/6 mr-2.5" />
                        )}
                        <div className="mt-2">
                            <h3 className="font-bold">{destinationType.name}</h3>
                            <p className="text-sm">{destinationType.short_description}</p>
                        </div>
                    </a>
                ))}
            </div>
        </>
    )
}

export const useDestinationTypes = (): {
    destinationTypes: DestinationType[]
    loading: boolean
    error: Error | null
} => {
    // The useDestinationTypes hook is used to retrieve the available destination
    // types for the user. We use the /api/projects/<project_id>/destination_types
    // endpoint to retrieve the available destination types, and we return the
    // destination types as an array of DestinationType objects.

    // We explicitly do not use kea or kea logics here, but rather simply fetch
    // and React.

    // If the request fails, we return undefined for the destination types, false
    // for loading, and the error for the error.
    const { currentTeam } = useValues(teamLogic)
    const [destinationTypes, setDestinationTypes] = useState<DestinationType[]>([])
    const [loading, setLoading] = useState(true)
    const [error, setError] = useState<Error | null>(null)

    useEffect(() => {
        if (currentTeam) {
            fetch(`/api/projects/${currentTeam.id}/destination-types`)
                .then(async (response) => {
                    if (response.ok) {
                        const data = (await response.json()) as DestinationTypesResponse
                        setDestinationTypes(data.destination_types)
                        setLoading(false)
                    } else {
                        setError(new Error('Failed to retrieve destination types'))
                        setLoading(false)
                    }
                })
                .catch((error) => {
                    setError(error)
                    setLoading(false)
                })
        }
    }, [currentTeam])

    return { destinationTypes, loading, error }
}

type DestinationTypesResponse = {
    destination_types: DestinationType[]
}

export type DestinationType = {
    id: string
    name: string
    description: string
    short_description: string
    icon_url: string
    config_schema: { [key: string]: any } // TODO: add proper typing for JSON schema
}
