import { SDKKey } from '~/types'

import { NodeInstallSnippet, NodeSetupSnippet } from '../sdk-install-instructions'
import { SDKInstallAngularInstructions } from '../sdk-install-instructions/angular'
import { FlagImplementationSnippet } from './flagImplementationSnippet'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'

export function FeatureFlagsAngularInstructions(): JSX.Element {
    return (
        <>
            <SDKInstallAngularInstructions />
            <LemonDivider thick dashed className="my-4" />
            <FlagImplementationSnippet sdkKey={SDKKey.JS_WEB} />
        </>
    )
}
