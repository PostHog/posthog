import { SDK } from '~/types'
import { IconOpenInNew } from 'lib/lemon-ui/icons'
import { Link } from 'lib/lemon-ui/Link'

export const SDKSnippet = ({
    sdk,
    sdkInstructionMap,
}: {
    sdk: SDK
    sdkInstructionMap: Record<string, () => JSX.Element>
}): JSX.Element => {
    const SDKInstructions = sdkInstructionMap[sdk.key]
    return SDKInstructions ? (
        <div>
            <div className="mb-8">
                <h3 className="text-xl font-bold mb-2">Integrate PostHog with {sdk.name}</h3>
                <Link className="" to={sdk.docsLink}>
                    Read the docs <IconOpenInNew />
                </Link>
            </div>
            <SDKInstructions />
        </div>
    ) : (
        <></>
    )
}
