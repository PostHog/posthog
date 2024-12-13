import { SDKKey } from '~/types'

import { SDKInstallFramerInstructions } from '../sdk-install-instructions/framer'
import { ExperimentsImplementationSnippet } from './ExperimentsImplementationSnippet'

export function ExperimentsFramerInstructions(): JSX.Element {
    return (
        <>
            <SDKInstallFramerInstructions />
            <ExperimentsImplementationSnippet sdkKey={SDKKey.JS_WEB} />
        </>
    )
}
