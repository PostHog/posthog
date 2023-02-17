import { LemonButton, LemonSelect } from '@posthog/lemon-ui'
import { useState } from 'react'
import { FeatureFlagInstructions } from './FeatureFlagInstructions'

export enum ClientLibraries {
    JavaScript = 'JavaScript',
    ReactNative = 'React Native',
    Android = 'Android',
    iOS = 'iOS',
}

export enum ServerLibraries {
    Node = 'Node',
    Python = 'Python',
    Ruby = 'Ruby',
    Go = 'Go',
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

    return (
        <div>
            {implementationStep === ImplementationSteps.LibrarySelection && (
                <div className="LibrarySelection">
                    Which library will you be implementing this feature flag in?
                    <LemonSelect
                        value={library}
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
                    <div>
                        For server libraries, we recommend implementing <b>local evaluation</b>. This improves
                        performance as it doesn't rely on additional network requests to handle returned feature flag
                        values because it's computed in the server's end directly. This requires: 1. Initializing the
                        library with your personal API key (found in user account settings) 2. Passing in all the person
                        and group properties the flag relies on
                        <a
                            href={'https://posthog.com/manual/feature-flags#server-side-local-evaluation'}
                            target="_blank"
                        >
                            Implementation details
                        </a>
                    </div>
                    <LemonButton
                        onClick={() => {
                            setShouldBootstrap(true)
                            setImplementationStep(ImplementationSteps.Bootstrapping)
                        }}
                    >
                        I'll want to do this
                    </LemonButton>
                    <LemonButton onClick={() => setImplementationStep(ImplementationSteps.Bootstrapping)}>
                        I'll skip this
                    </LemonButton>
                </div>
            )}
            {implementationStep === ImplementationSteps.Bootstrapping && (
                <div>
                    <div>
                        We recommend <b>bootstrapping</b> if you need to have your feature flags available immediately
                        as there's a delay between initial loading of the library and feature flags becoming available
                        to use.
                    </div>
                    <LemonButton onClick={() => setImplementationStep(ImplementationSteps.Summary)}>Finish</LemonButton>
                </div>
            )}
            {implementationStep === ImplementationSteps.Summary && (
                <>
                    <FeatureFlagInstructions featureFlagKey={'my-flag'} />
                    {shouldBootstrap && <div>bootstrapping instructions</div>}
                </>
            )}
        </div>
    )
}
