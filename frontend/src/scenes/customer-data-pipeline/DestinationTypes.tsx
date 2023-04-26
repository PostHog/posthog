import SkeletonImage from 'antd/lib/skeleton/Image'
import { PageHeader } from 'lib/components/PageHeader'
import { Link } from 'lib/lemon-ui/Link'
import { useMemo } from 'react'
import { urls } from 'scenes/urls'

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

    const { destinationTypes } = useDestinationTypes()

    return (
        <>
            <PageHeader title="Destinations" caption="Connect your data to your favorite tools." />
            <div className="grid grid-cols-4 gap-4">
                {destinationTypes.map((destinationType) => (
                    <Link
                        key={destinationType.id}
                        className="border rounded text-left flex flex-row p-2.5 block items-center"
                        to={urls.createDestinationOfType(destinationType.id)}
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
                    </Link>
                ))}
            </div>
        </>
    )
}

export const useDestinationTypes = (): {
    destinationTypes: DestinationType[]
} => {
    // Retrieve the destination types. This hook is structured such that it
    // could be used to load the data asynchronously, but for now we just load
    // data locally.

    const destinationTypes: DestinationType[] = useMemo(
        () => [
            {
                id: 'webhook',
                name: 'Webhook',
                short_description: 'Send data to any destination with a webhook.',
                description: 'Send data to any destination with a webhook.',
                config_schema: {
                    type: 'object',
                    properties: {
                        url: {
                            type: 'string',
                            required: true,
                            placeholder: 'https://example.com',
                            label: 'URL',
                        },
                        headers: {
                            type: 'array',
                            label: 'Headers',
                            description: 'Headers to send with the request.',
                            items: {
                                type: 'object',
                                properties: {
                                    key: {
                                        type: 'string',
                                        required: true,
                                        label: 'Key',
                                    },
                                    value: {
                                        type: 'string',
                                        required: true,
                                        label: 'Value',
                                    },
                                },
                            },
                        },
                    },
                },
                icon_url:
                    'data:image/jpeg;base64,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',
            },
            {
                id: 'amplitude',
                name: 'Amplitude',
                short_description: 'Amplitude is a product analytics platform that helps you understand your users.',
                description: 'Amplitude is a product analytics platform that helps you understand your users.',
                config_schema: {
                    type: 'object',
                    properties: {
                        api_key: {
                            type: 'string',
                            required: true,
                            placeholder: 'Your Amplitude API key',
                            label: 'API Key',
                        },
                    },
                },
                icon_url:
                    'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAIAAAACFCAMAAACkLQBKAAAAIGNIUk0AAHomAACAhAAA+gAAAIDoAAB1MAAA6mAAADqYAAAXcJy6UTwAAAMAUExURQAAAB5h8BZHsR5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8B5h8P///wHlXKQAAAD+dFJOUwAAAAYbOFt/n7vT4u72/P777eHRuZ19WDYZBQkmUYOy1ez5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',
            },
            {
                id: 'optimizely',
                name: 'Optimizely',
                description:
                    'Optimizely is a feature management platform that enables teams to deliver continuous experimentation and personalization at scale.',
                short_description: 'Feature management platform',
                icon_url:
                    'data:image/png;base64,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',
                config_schema: {
                    type: 'object',
                    properties: {
                        api_key: {
                            type: 'string',
                            title: 'API Key',
                            description: 'Your Optimizely API key.',
                            default: '',
                        },
                    },
                },
            },
            {
                id: 'taplytics',
                name: 'Taplytics',
                short_description: 'A/B Testing and Feature Management',
                description: 'Taplytics is a mobile A/B testing and feature management platform.',
                icon_url: '',
                config_schema: {
                    type: 'object',
                    properties: {
                        api_key: {
                            type: 'string',
                            title: 'API Key',
                        },
                    },
                },
            },
            {
                id: 'mixpanel',
                name: 'Mixpanel',
                short_description: 'Analytics',
                description: 'Mixpanel is a mobile analytics platform.',
                icon_url: '',
                config_schema: {
                    type: 'object',
                    properties: {
                        api_key: {
                            type: 'string',
                            title: 'API Key',
                        },
                    },
                },
            },
        ],
        []
    )

    return { destinationTypes }
}

export type DestinationType = {
    id: string
    name: string
    description: string
    short_description: string
    icon_url: string
    config_schema: { [key: string]: any } // TODO: add proper typing for JSON schema
}

export default DestinationTypes // The default export is assumed to be the Scene component.
