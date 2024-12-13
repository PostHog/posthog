import { SDKKey } from '~/types'

import { SDKInstallVueInstructions } from '../sdk-install-instructions/vue'
import { ExperimentsImplementationSnippet } from './ExperimentsImplementationSnippet'

export function ExperimentsVueInstructions(): JSX.Element {
    return (
        <>
            <SDKInstallVueInstructions />
            <ExperimentsImplementationSnippet sdkKey={SDKKey.JS_WEB} />
        </>
    )
}
