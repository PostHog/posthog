import { LemonDivider } from 'lib/lemon-ui/LemonDivider'

import { SDKKey } from '~/types'

import { SDKInstallAngularInstructions } from '../sdk-install-instructions'
import { ExperimentsImplementationSnippet } from './ExperimentsImplementationSnippet'

export function ExperimentsAngularInstructions(): JSX.Element {
    return (
        <>
            <SDKInstallAngularInstructions />
            <LemonDivider thick dashed className="my-4" />
            <ExperimentsImplementationSnippet sdkKey={SDKKey.JS_WEB} />
        </>
    )
}
