import { LemonDivider } from '@posthog/lemon-ui'

import { SDKKey } from '~/types'

import { SDKInstallPHPInstructions } from '../sdk-install-instructions'
import { ExperimentsImplementationSnippet } from './ExperimentsImplementationSnippet'

export function ExperimentsPHPInstructions(): JSX.Element {
    return (
        <>
            <SDKInstallPHPInstructions />
            <LemonDivider thick dashed className="my-4" />
            <ExperimentsImplementationSnippet sdkKey={SDKKey.PHP} />
        </>
    )
}
