import { SDKKey } from '~/types'

import { SDKInstallFlutterInstructions } from '../sdk-install-instructions'
import { ExperimentsImplementationSnippet } from './ExperimentsImplementationSnippet'

export function ExperimentsFlutterInstructions(): JSX.Element {
    return (
        <>
            <SDKInstallFlutterInstructions />
            <ExperimentsImplementationSnippet sdkKey={SDKKey.FLUTTER} />
        </>
    )
}
