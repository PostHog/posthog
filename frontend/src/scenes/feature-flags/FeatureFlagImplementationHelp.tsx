import { LemonButton, LemonSelect } from '@posthog/lemon-ui'
import { IconArrowLeft } from 'lib/lemon-ui/icons'
import { useState } from 'react'
import {
    FeatureFlagBootstrappingInstructions,
    FeatureFlagInstructions,
    FeatureFlagLocalEvaluationInstructions,
} from './FeatureFlagInstructions'

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

const AllLibraries = { ...ClientLibraries, ...ServerLibraries }
type AllLibraries = ClientLibraries | ServerLibraries

enum ImplementationSteps {
    LibrarySelection = 1,
    LocalEvaluation = 2,
    Bootstrapping = 3,
    Summary = 4,
}

export function FeatureFlagImplementationHelp(): JSX.Element {
    const [implementationStep, setImplementationStep] = useState(ImplementationSteps.LibrarySelection)
    const [library, setLibrary] = useState<AllLibraries>(AllLibraries.JavaScript)
    const [shouldBootstrap, setShouldBootstrap] = useState(false)
    const [shouldLocalEval, setShouldLocalEval] = useState(false)

    return (
        <div className="mb-4 p-2">
            {implementationStep === ImplementationSteps.LibrarySelection && (
                <div className="LibrarySelection">
                    Which library will you be implementing this feature flag in?
                    <LemonSelect
                        className="mt-4"
                        dropdownMaxContentWidth
                        onSelect={(val) => setLibrary(val)}
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
                    <div className="flex justify-end">
                        <LemonButton
                            type="primary"
                            onClick={() => {
                                if (Object.values(ServerLibraries).includes(library)) {
                                    setImplementationStep(ImplementationSteps.LocalEvaluation)
                                } else {
                                    if ([AllLibraries.Android, AllLibraries.iOS].includes(library)) {
                                        setImplementationStep(ImplementationSteps.Summary)
                                    } else {
                                        setImplementationStep(ImplementationSteps.Bootstrapping)
                                    }
                                }
                            }}
                        >
                            Next
                        </LemonButton>
                    </div>
                </div>
            )}
            {implementationStep === ImplementationSteps.LocalEvaluation && (
                <div>
                    <LemonButton
                        icon={<IconArrowLeft />}
                        className="mb-4"
                        size="small"
                        onClick={() => setImplementationStep(ImplementationSteps.LibrarySelection)}
                    >
                        Library selection
                    </LemonButton>
                    <div className="pl-2">
                        <h3>Local evaluation</h3>
                        <span>
                            For server libraries, we recommend implementing <b>local evaluation</b>. This improves
                            performance by reducing additional network requests.
                        </span>
                        <ul className="mb-2">
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
                            <b>Read more</b>
                        </a>
                    </div>
                    <div className="flex justify-between mt-4">
                        <LemonButton
                            type="secondary"
                            size="small"
                            onClick={() => {
                                setShouldLocalEval(false)
                                setImplementationStep(ImplementationSteps.Summary)
                            }}
                        >
                            I'll skip this
                        </LemonButton>
                        <LemonButton
                            type="primary"
                            size="small"
                            onClick={() => {
                                setShouldLocalEval(true)
                                setImplementationStep(ImplementationSteps.Summary)
                            }}
                        >
                            Add this to my summary
                        </LemonButton>
                    </div>
                </div>
            )}
            {implementationStep === ImplementationSteps.Bootstrapping && (
                <div>
                    <LemonButton
                        icon={<IconArrowLeft />}
                        size="small"
                        className="mb-4"
                        onClick={() => setImplementationStep(ImplementationSteps.LibrarySelection)}
                    >
                        Library selection
                    </LemonButton>
                    <div>
                        <h3>Bootstrapping</h3>
                        <div>
                            For client side libraries, we recommend <b>bootstrapping</b> if you need to have your
                            feature flags immediately available since there's a delay between initial loading of the
                            library and feature flags becoming available to use.
                        </div>
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
                    <FeatureFlagInstructions featureFlagKey={'my-flag'} language={library} />
                    {shouldLocalEval && (
                        <div className="mt-4">
                            <h4>Local evaluation</h4>
                            <div className="mb-4">
                                <p>
                                    All feature flag evaluation requires an API request to your PostHog servers to get a
                                    response. However, where latency matters, you can evaluate flags locally.
                                </p>
                                <p>This is much faster, and requires two things to work:</p>
                                <ul>
                                    <li>
                                        1. Initializing the library with your personal API key (found in user account
                                        settings)
                                    </li>
                                    <li>2. Passing in all the person and group properties the flag relies on</li>
                                </ul>
                            </div>
                            <FeatureFlagLocalEvaluationInstructions featureFlagKey={'my-flag'} language={library} />
                        </div>
                    )}
                    {shouldBootstrap && (
                        <div className="mt-4">
                            <h4>Bootstrapping instructions</h4>
                            <div className="mb-4">
                                There is a delay between loading the library and feature flags becoming available to
                                use. For some cases, like redirecting users to a different page based on a feature flag
                                this won't work because flags load after the redirect logic occurs. In cases where you
                                want flags to be immediately available on page load, you can bootstrap them.
                            </div>
                            <FeatureFlagBootstrappingInstructions language={library} />
                        </div>
                    )}
                </div>
            )}
        </div>
    )
}
