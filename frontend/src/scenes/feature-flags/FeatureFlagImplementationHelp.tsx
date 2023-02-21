import { LemonButton, LemonSelect } from '@posthog/lemon-ui'
import { IconArrowLeft } from 'lib/lemon-ui/icons'
import { useState } from 'react'
import { FeatureFlagInstructions } from './FeatureFlagInstructions'

export enum ClientLibraries {
    JavaScript = 'JavaScript',
    ReactNative = 'React Native',
    Android = 'Android',
    iOS = 'iOS',
}

export enum ServerLibraries {
    Node = 'Node.js',
    Python = 'Python',
    Ruby = 'Ruby',
    Golang = 'Golang',
    PHP = 'PHP',
}

const allLibraries = { ...ClientLibraries, ...ServerLibraries }

enum ImplementationSteps {
    LibrarySelection = 1,
    LocalEvaluation = 2,
    Bootstrapping = 3,
    Summary = 4,
}

export function FeatureFlagImplementationHelp(): JSX.Element {
    const [implementationStep, setImplementationStep] = useState(ImplementationSteps.LibrarySelection)
    const [library, setLibrary] = useState(allLibraries.JavaScript)
    const [shouldBootstrap, setShouldBootstrap] = useState(false)
    const [shouldLocalEval, setShouldLocalEval] = useState(false)

    return (
        <div className="mb-4">
            {implementationStep === ImplementationSteps.LibrarySelection && (
                <div className="LibrarySelection">
                    Which library will you be implementing this feature flag in?
                    <LemonSelect
                        className="mt-4"
                        dropdownMaxContentWidth
                        onSelect={(val) => {
                            setLibrary(val)
                            if (val in ServerLibraries) {
                                setImplementationStep(ImplementationSteps.LocalEvaluation)
                            } else {
                                setImplementationStep(ImplementationSteps.Bootstrapping)
                            }
                        }}
                        options={[
                            {
                                title: 'Client libraries',
                                options: [
                                    ...(Object.keys(ClientLibraries) as Array<ClientLibraries>).map(
                                        (clientLibrary) => ({
                                            value: ClientLibraries[clientLibrary],
                                            label: clientLibrary,
                                        })
                                    ),
                                ],
                            },
                            {
                                title: 'Server libraries',
                                options: [
                                    ...(Object.keys(ServerLibraries) as Array<ServerLibraries>).map(
                                        (serverLibrary) => ({
                                            value: ServerLibraries[serverLibrary],
                                            label: serverLibrary,
                                        })
                                    ),
                                ],
                            },
                        ]}
                    />
                </div>
            )}
            {implementationStep === ImplementationSteps.LocalEvaluation && (
                <div>
                    <LemonButton
                        icon={<IconArrowLeft />}
                        size="small"
                        onClick={() => setImplementationStep(ImplementationSteps.LibrarySelection)}
                    >
                        Library selection
                    </LemonButton>
                    <div>
                        <span>
                            For server libraries, we recommend implementing <b>local evaluation</b>. This improves
                            performance as it doesn't rely on additional network requests.
                        </span>
                        <ul>
                            This requires:
                            <li>
                                1. Initializing the library with your personal API key (found in user account settings)
                            </li>
                            <li>2. Passing in all the person and group properties the flag relies on</li>
                        </ul>
                        <a
                            href={'https://posthog.com/manual/feature-flags#server-side-local-evaluation'}
                            target="_blank"
                        >
                            Code example details
                        </a>
                    </div>
                    <div className="flex justify-between mt-4">
                        <LemonButton
                            type="secondary"
                            size="small"
                            onClick={() => {
                                setShouldLocalEval(false)
                                setImplementationStep(ImplementationSteps.Bootstrapping)
                            }}
                        >
                            I'll skip this
                        </LemonButton>
                        <LemonButton
                            type="primary"
                            size="small"
                            onClick={() => {
                                setShouldLocalEval(true)
                                setImplementationStep(ImplementationSteps.Bootstrapping)
                            }}
                        >
                            Add this to my summary
                        </LemonButton>
                    </div>
                </div>
            )}
            {implementationStep === ImplementationSteps.Bootstrapping && (
                <div>
                    <div>
                        If you need to have your feature flags immediately available as there's a delay between initial
                        loading of the library and feature flags becoming available to use, we recommend{' '}
                        <b>bootstrapping</b>.
                    </div>
                    <div className="flex justify-between mt-4">
                        <LemonButton
                            type="secondary"
                            size="small"
                            onClick={() => setImplementationStep(ImplementationSteps.Summary)}
                        >
                            I'll skip this
                        </LemonButton>
                        <LemonButton
                            type="primary"
                            size="small"
                            onClick={() => {
                                setShouldBootstrap(true)
                                setImplementationStep(ImplementationSteps.Summary)
                            }}
                        >
                            Add this to my summary
                        </LemonButton>
                    </div>
                </div>
            )}
            {implementationStep === ImplementationSteps.Summary && (
                <div>
                    <h3>Summary</h3>
                    Library: {library}
                    <FeatureFlagInstructions featureFlagKey={'my-flag'} language={library} />
                    {shouldLocalEval && <div />}
                    {shouldBootstrap && <div>bootstrapping instructions</div>}
                </div>
            )}
        </div>
    )
}
