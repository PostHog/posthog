import { SDKKey } from '~/types'

import { SDKInstallWebflowInstructions } from '../sdk-install-instructions/webflow'
import { ExperimentsImplementationSnippet } from './ExperimentsImplementationSnippet'

export function ExperimentsWebflowInstructions(): JSX.Element {
    return (
        <>
            <SDKInstallWebflowInstructions />
            <ExperimentsImplementationSnippet sdkKey={SDKKey.JS_WEB} />
        </>
    )
}
