import { Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { SDKKey } from '~/types'

import { ALL_SDKS } from '../../control/sdks/allSDKs'

/** A row of small logos for the stacks a platform supports, named on hover. */
export function StackLogos({ sdkKeys }: { sdkKeys: SDKKey[] }): JSX.Element {
    const sdks = sdkKeys.flatMap((key) => ALL_SDKS.find((sdk) => sdk.key === key) ?? [])

    return (
        <span className="flex flex-wrap items-center gap-1.5">
            {sdks.map((sdk) => (
                <Tooltip key={sdk.key}>
                    <TooltipTrigger
                        render={<span className="flex size-4 items-center justify-center [&>*]:size-4" />}
                        aria-label={sdk.name}
                    >
                        {typeof sdk.image === 'string' ? (
                            <img src={sdk.image} alt="" />
                        ) : typeof sdk.image === 'object' && 'default' in sdk.image ? (
                            <img src={sdk.image.default} alt="" />
                        ) : (
                            sdk.image
                        )}
                    </TooltipTrigger>
                    <TooltipContent>{sdk.name}</TooltipContent>
                </Tooltip>
            ))}
        </span>
    )
}
