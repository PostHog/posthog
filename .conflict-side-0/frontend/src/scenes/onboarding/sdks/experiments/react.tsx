import { LemonDivider } from 'lib/lemon-ui/LemonDivider'

import { SDKKey } from '~/types'

import { SDKInstallReactInstructions } from '../sdk-install-instructions/react'
import { ExperimentsImplementationSnippet } from './ExperimentsImplementationSnippet'

export function ExperimentsReactInstructions(): JSX.Element {
    return (
        <>
            <SDKInstallReactInstructions hideWizard />
            <LemonDivider thick dashed className="my-4" />
            <ExperimentsImplementationSnippet sdkKey={SDKKey.REACT} />
        </>
    )
}
