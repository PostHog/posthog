//
// A react component that allows the user to create an event destination of the
// specified type. The user can specify the name of the destination, and the
// destination's configuration. Each destination has a different configuration,
// with valid configuration specifed by the configSchema property of the
// specification.

import { router } from 'kea-router'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { DestinationType, useDestinationTypes } from './DestinationTypes'
import { useState } from 'react'
import { teamLogic } from 'scenes/teamLogic'
import { useValues } from 'kea'
import { Destination, DestinationData } from './Destinations'
import MonacoEditor, { EditorProps as MonacoEditorProps } from '@monaco-editor/react'
import { Monaco } from '@monaco-editor/react'
import { Divider } from 'antd'
import { useCallback } from 'react'
import { useMemo } from 'react'
import { urls } from 'scenes/urls'
import { lemonToast } from 'lib/lemon-ui/lemonToast'
import { LemonButton } from 'lib/lemon-ui/LemonButton'

const createDestination = async (teamId: number, destinationData: DestinationData): Promise<Destination> => {
    // Create a destination with the specified data. The destination data
    // includes the name, description, type, and configuration of the
    // destination.

    const response = await fetch(`/api/projects/${teamId}/destinations`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify(destinationData),
    })

    if (!response.ok) {
        throw new Error('Failed to create destination')
    }

    return (await response.json()) as Destination
}

const useCreateDestination = (): {
    creating: boolean
    error: Error | null
    create: (teamId: number, destinationData: DestinationData) => Promise<Destination>
} => {
    // A hook that creates a destination with the specified data. It provides a
    // creating and error state, as well as a callback that can be used e.g. for
    // onClick handlers.
    const [creating, setCreating] = useState(false)
    const [error, setError] = useState<Error | null>(null)

    const create = useCallback(async (teamId: number, destinationData: DestinationData) => {
        setCreating(true)
        setError(null)

        try {
            return await createDestination(teamId, destinationData)
        } catch (error) {
            setError(error as Error)
            throw error
        } finally {
            setCreating(false)
        }
    }, [])

    return { creating, error, create }
}

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

    const { destinationType } = useDestinationType('webhook')

    const [destination, setDestination] = useState<DestinationData>({
        name: '',
        description: '',
        type: 'amplitude',
        config: {
            api_key: 'asdf',
        },
        mappings: [],
    })

    const { currentTeam } = useValues(teamLogic)

    const { creating, create } = useCreateDestination()

    if (!currentTeam) {
        return <div>Team not found</div>
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
            <form>
                <div className="mt-8">
                    <div className="mb-4">
                        <label className="block text-gray-700 text-sm font-bold mb-2">Destination name</label>
                        <input
                            className="shadow appearance-none border rounded w-full py-2 px-3 text-gray-700 leading-tight focus:outline-none focus:shadow-outline"
                            type="text"
                            placeholder="Destination name"
                            value={destination.name}
                            onChange={(event) => setDestination({ ...destination, name: event.target.value })}
                        />

                        <label className="block text-gray-700 text-sm font-bold mb-2">Destination description</label>
                        <input
                            className="shadow appearance-none border rounded w-full py-2 px-3 text-gray-700 leading-tight focus:outline-none focus:shadow-outline"
                            type="text"
                            placeholder="Destination description"
                            value={destination.description}
                            onChange={(event) => setDestination({ ...destination, description: event.target.value })}
                        />
                    </div>
                    <div className="mb-4">
                        <label className="block text-gray-700 text-sm font-bold mb-2">Destination configuration</label>
                    </div>
                    {destination.type === 'webhook' ? (
                        <>
                            {/* For webhooks we can configure the url, and a list of headers to include */}
                            <div className="mb-4">
                                <label className="block text-gray-700 text-sm font-bold mb-2">URL</label>
                                <input
                                    className="shadow appearance-none border rounded w-full py-2 px-3 text-gray-700 leading-tight focus:outline-none focus:shadow-outline"
                                    type="text"
                                    placeholder="URL"
                                    value={destination.config.url}
                                    onChange={(event) =>
                                        setDestination({
                                            ...destination,
                                            config: { ...destination.config, url: event.target.value },
                                        })
                                    }
                                />
                            </div>
                            <div className="mb-4">
                                <label className="block text-gray-700 text-sm font-bold mb-2">Headers</label>
                                <div className="flex flex-col">
                                    {destination.config.headers.map((header, index) => (
                                        <div className="flex flex-row mb-2" key={index}>
                                            <input
                                                className="shadow appearance-none border rounded w-full py-2 px-3 text-gray-700 leading-tight focus:outline-none focus:shadow-outline"
                                                type="text"
                                                placeholder="Header name"
                                                value={header.name}
                                                onChange={(event) =>
                                                    setDestination({
                                                        ...destination,
                                                        config: {
                                                            ...destination.config,
                                                            headers: destination.config.headers.map((header, i) =>
                                                                i === index
                                                                    ? { ...header, name: event.target.value }
                                                                    : header
                                                            ),
                                                        },
                                                    })
                                                }
                                            />
                                            <input
                                                className="shadow appearance-none border rounded w-full py-2 px-3 text-gray-700 leading-tight focus:outline-none focus:shadow-outline"
                                                type="text"
                                                placeholder="Header value"
                                                value={header.value}
                                                onChange={(event) =>
                                                    setDestination({
                                                        ...destination,
                                                        config: {
                                                            ...destination.config,
                                                            headers: destination.config.headers.map((header, i) =>
                                                                i === index
                                                                    ? { ...header, value: event.target.value }
                                                                    : header
                                                            ),
                                                        },
                                                    })
                                                }
                                            />
                                            <LemonButton
                                                className="bg-red-500 hover:bg-red-700 text-white font-bold py-2 px-4 rounded"
                                                onClick={() =>
                                                    setDestination({
                                                        ...destination,
                                                        config: {
                                                            ...destination.config,
                                                            headers: destination.config.headers.filter(
                                                                (_, i) => i !== index
                                                            ),
                                                        },
                                                    })
                                                }
                                            >
                                                Delete
                                            </LemonButton>
                                        </div>
                                    ))}
                                    <LemonButton
                                        className="bg-green-500 hover:bg-green-700 text-white font-bold py-2 px-4 rounded"
                                        onClick={() =>
                                            setDestination({
                                                ...destination,
                                                config: {
                                                    ...destination.config,
                                                    headers: [...destination.config.headers, { name: '', value: '' }],
                                                },
                                            })
                                        }
                                    >
                                        Add header
                                    </LemonButton>
                                </div>
                            </div>
                        </>
                    ) : destination.type === 'amplitude' ? (
                        <div className="mb-4">
                            <label className="block text-gray-700 text-sm font-bold mb-2">API key</label>
                            <input
                                className="shadow appearance-none border rounded w-full py-2 px-3 text-gray-700 leading-tight focus:outline-none focus:shadow-outline"
                                type="text"
                                placeholder="API key"
                                value={destination.config.api_key}
                                onChange={(event) =>
                                    setDestination({
                                        ...destination,
                                        config: { ...destination.config, api_key: event.target.value },
                                    })
                                }
                            />
                        </div>
                    ) : null}
                    <div className="mb-4">
                        <label className="block text-gray-700 text-sm font-bold mb-2">Event mappings</label>

                        <div className="flex flex-col">
                            {destination.mappings.map((mapping, index) => (
                                <div className="flex flex-row" key={index}>
                                    <div className="flex flex-col w-1/2">
                                        <label className="block text-gray-700 text-sm font-bold mb-2">Filter</label>
                                        <JsonataEditor
                                            language="jsonata"
                                            loading={<Spinner />}
                                            value={mapping.filter.value}
                                            onChange={(value) => {
                                                const newMapping = {
                                                    ...mapping,
                                                    filter: { ...mapping.filter, value: value ?? '' },
                                                }
                                                const newMappings = [...destination.mappings]
                                                newMappings[index] = newMapping
                                                setDestination({ ...destination, mappings: newMappings })
                                            }}
                                        />
                                    </div>
                                    <div className="flex flex-col w-1/2">
                                        <label className="block text-gray-700 text-sm font-bold mb-2">
                                            Transformation
                                        </label>
                                        <JsonataEditor
                                            language="jsonata"
                                            loading={<Spinner />}
                                            height="150px"
                                            value={mapping.transformation.value}
                                            onChange={(value) => {
                                                const newMapping = {
                                                    ...mapping,
                                                    transformation: { ...mapping.transformation, value: value ?? '' },
                                                }
                                                const newMappings = [...destination.mappings]
                                                newMappings[index] = newMapping
                                                setDestination({ ...destination, mappings: newMappings })
                                            }}
                                        />
                                    </div>
                                    <div className="flex flex-col">
                                        <label className="block text-gray-700 text-sm font-bold mb-2">&nbsp;</label>
                                        <LemonButton
                                            className="bg-red-500 hover:bg-red-700 text-white font-bold py-2 px-4 rounded focus:outline-none focus:shadow-outline"
                                            onClick={() => {
                                                const newMappings = [...destination.mappings]
                                                newMappings.splice(index, 1)
                                                setDestination({ ...destination, mappings: newMappings })
                                            }}
                                        >
                                            Delete
                                        </LemonButton>
                                    </div>
                                </div>
                            ))}
                        </div>

                        <Divider />

                        <LemonButton
                            className="bg-blue-500 hover:bg-blue-700 font-bold py-2 px-4 rounded focus:outline-none focus:shadow-outline"
                            onClick={() => {
                                const newMappings = [...destination.mappings]
                                newMappings.push({
                                    filter: {
                                        type: 'jsonata',
                                        value: '',
                                    },
                                    transformation: {
                                        type: 'jsonata',
                                        value: '',
                                    },
                                })
                                setDestination({ ...destination, mappings: newMappings })
                            }}
                        >
                            Create mapping
                        </LemonButton>
                    </div>
                </div>

                <div className="mt-8">
                    <LemonButton
                        className="bg-blue-500 hover:bg-blue-700 font-bold py-2 px-4 rounded focus:outline-none focus:shadow-outline"
                        onClick={() => {
                            create(currentTeam.id, destination)
                                .then(() => {
                                    lemonToast.success('Destination created')
                                    router.actions.push(urls.destinations())
                                })
                                .catch((error) => {
                                    lemonToast.error(error.message)
                                })
                        }}
                        disabled={creating}
                    >
                        Create
                    </LemonButton>
                    <LemonButton
                        className="bg-gray-500 hover:bg-gray-700 font-bold py-2 px-4 rounded focus:outline-none focus:shadow-outline"
                        to={urls.destinationTypes()}
                    >
                        Cancel
                    </LemonButton>
                </div>
            </form>
        </>
    )
}

const useDestinationType = (type: string): { destinationType: DestinationType | undefined } => {
    // Get the specified destination type. This is used e.g. to get the URL for
    // the destination type's logo.

    const { destinationTypes } = useDestinationTypes()

    const destinationTypesLookup = useMemo(
        () => Object.fromEntries(destinationTypes.map((destinationType) => [destinationType.id, destinationType])),
        [destinationTypes]
    )

    return { destinationType: destinationTypesLookup[type] }
}

export default CreateDestinationOfType // The default export is assumed to be the Scene component.

/**
 * © Copyright IBM Corp. 2020 All Rights Reserved
 *   Project name: JSONata
 *   This project is licensed under the MIT License, see LICENSE
 */

const registerJsonata = (monaco: Monaco): void => {
    // Register a new language
    monaco.languages.register({ id: 'jsonata' })

    // Register a tokens provider for the language
    monaco.languages.setMonarchTokensProvider('jsonata', {
        tokenizer: {
            root: [
                [/\/\*.*\*\//, 'jsonata-comment'],
                [/'.*'/, 'jsonata-string'],
                [/".*"/, 'jsonata-string'],
                [/\$[a-zA-Z0-9_]*/, 'jsonata-variable'],
                [/[a-zA-Z0-9_]+/, 'jsonata-names'],
            ],
        },
    })

    const brackets = [
        { open: '(', close: ')' },
        { open: '[', close: ']' },
        { open: '{', close: '}' },
        { open: '"', close: '"' },
        { open: "'", close: "'" },
        { open: '`', close: '`' },
    ]
    monaco.languages.setLanguageConfiguration('jsonata', {
        brackets: [
            ['(', ')'],
            ['[', ']'],
            ['{', '}'],
        ],
        autoClosingPairs: brackets,
        surroundingPairs: brackets,
        indentationRules: {
            // ^(.*\*/)?\s*\}.*$
            decreaseIndentPattern: /^((?!.*?\/\*).*\*\/)?\s*[}\])].*$/,
            // ^.*\{[^}"']*$
            increaseIndentPattern: /^((?!\/\/).)*(\{[^}"'`]*|\([^)"'`]*|\[[^\]"'`]*)$/,
        },
    })

    // Define a new theme that contains only rules that match this language
    monaco.editor.defineTheme('jsonataTheme', {
        base: 'vs',
        inherit: true,
        rules: [
            { token: 'jsonata-string', foreground: 'a00000' },
            { token: 'jsonata-comment', foreground: '008000' },
            { token: 'jsonata-variable', foreground: 'ff4000' },
            { token: 'jsonata-names', foreground: '0000c0' },
        ],
        colors: {
            'editor.background': '#fffffb',
        },
    })
}

const JsonataEditor = (args: MonacoEditorProps): JSX.Element => {
    // An editor for the JSONata expression that is used to transform
    // the event before it is sent to the destination. Has the same types as the
    // MonacoEditor component.
    return <MonacoEditor {...args} language="jsonata" beforeMount={registerJsonata} />
}
