import { LemonDivider } from '@posthog/lemon-ui'

import { SDKKey } from '~/types'

import { SDKInstallRubyInstructions } from '../sdk-install-instructions'
import { ExperimentsImplementationSnippet } from './ExperimentsImplementationSnippet'

export function ExperimentsRubyInstructions(): JSX.Element {
    return (
        <>
            <SDKInstallRubyInstructions />
            <LemonDivider thick dashed className="my-4" />
            <ExperimentsImplementationSnippet sdkKey={SDKKey.RUBY} />
        </>
    )
}
