import { LemonDivider } from '@posthog/lemon-ui'

import { SDKKey } from '~/types'

import { SDKInstallDjangoInstructions } from '../sdk-install-instructions'
import { ExperimentsImplementationSnippet } from './ExperimentsImplementationSnippet'

export function ExperimentsDjangoInstructions(): JSX.Element {
    return (
        <>
            <SDKInstallDjangoInstructions />
            <LemonDivider thick dashed className="my-4" />
            <ExperimentsImplementationSnippet sdkKey={SDKKey.PYTHON} />
        </>
    )
}
