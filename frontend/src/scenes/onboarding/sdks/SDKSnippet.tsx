import { SDK } from '~/types'
import { IconOpenInNew } from 'lib/lemon-ui/icons'
import { Link } from 'lib/lemon-ui/Link'

export const SDKSnippet = ({ sdk, sdkInstructions }: { sdk: SDK; sdkInstructions: () => JSX.Element }): JSX.Element => {
    return (
        <div>
            <div className="mb-8">
                <h3 className="text-xl font-bold mb-2">Integrate PostHog with {sdk.name}</h3>
                <Link className="" to={sdk.docsLink} target="_blank">
                    Read the docs <IconOpenInNew />
                </Link>
            </div>
            {sdkInstructions()}
        </div>
    )
}
