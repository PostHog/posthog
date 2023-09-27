import { JSSnippet } from 'lib/components/JSSnippet'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { FlagImplementationSnippet } from './flagImplementationSnippet'
import { SDKKey } from '~/types'
import { JSInstallSnippet, JSSetupSnippet } from '../sdk-install-instructions'

export function FeatureFlagsJSWebInstructions(): JSX.Element {
    return (
        <>
            <h3>Option 1. Code snippet</h3>
            <p>
                Just add this snippet to your website within the <code>&lt;head&gt;</code> tag and you'll be ready to
                start using feature flags.{' '}
            </p>
            <JSSnippet />
            <LemonDivider thick dashed className="my-4" />
            <h3>Option 2. Javascript Library</h3>
            <h4>Install the package</h4>
            <JSInstallSnippet />
            <h4>Initialize</h4>
            <JSSetupSnippet />
            <LemonDivider thick dashed className="my-4" />
            <FlagImplementationSnippet sdkKey={SDKKey.JS_WEB} />
        </>
    )
}
