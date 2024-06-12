import { SDKKey } from '~/types'

import { SDKInstallAngularInstructions } from '../sdk-install-instructions/angular'
import { FlagImplementationSnippet } from './flagImplementationSnippet'

export function FeatureFlagsAngularInstructions(): JSX.Element {
    return (
        <>
            <SDKInstallAngularInstructions />
            <FlagImplementationSnippet sdkKey={SDKKey.JS_WEB} />
        </>
    )
}
