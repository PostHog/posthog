import { memo } from 'react'

import { IconCheck, IconInfo, IconX } from '@posthog/icons'
import { LemonDivider, Tooltip } from '@posthog/lemon-ui'

import { isObject } from 'lib/utils'
import { cn } from 'lib/utils/css-classes'

import { PlatformSupport, PlatformSupportConfig } from './types'

type SupportedPlatformProps = {
    config: PlatformSupportConfig
}

function SupportedPlatform({ label, platform }: { label: string; platform: PlatformSupport | undefined }): JSX.Element {
    const supportedSinceVersion = isObject(platform) && typeof platform?.version === 'string' ? platform.version : false
    const note = isObject(platform) ? platform.note : undefined

    const node = (
        <div
            className={cn(
                supportedSinceVersion ? 'bg-fill-success-highlight' : 'bg-fill-warning-highlight',
                'px-1 py-0.5 h-full flex items-center gap-1',
                { 'cursor-help': note && supportedSinceVersion }
            )}
        >
            {note ? <IconInfo /> : supportedSinceVersion ? <IconCheck /> : <IconX />} {label}
        </div>
    )
    let tooltip = null
    if (supportedSinceVersion || note) {
        tooltip = (
            <div className="flex flex-col gap-1 cursor-help">
                {supportedSinceVersion && <div>Since version {supportedSinceVersion}</div>}
                {note && <div>{note}</div>}
            </div>
        )
    }
    if (tooltip) {
        return (
            <Tooltip delayMs={200} title={tooltip}>
                {node}
            </Tooltip>
        )
    }
    return node
}

export const SupportedPlatforms = memo(function SupportedPlatforms({
    config,
}: SupportedPlatformProps): JSX.Element | null {
    const allSupported = config && Object.keys(config).length === 5 && Object.values(config).every((value) => !!value)
    return allSupported ? null : (
        <div className="text-xs inline-flex flex-row bg-primary rounded items-center border overflow-hidden mb-2 w-fit">
            <Tooltip delayMs={200} title="We support lots of platforms! But not every feature works everywhere (yet)">
                <span className="px-1 py-0.5 font-semibold cursor-help">Supported platforms:</span>
            </Tooltip>
            <LemonDivider vertical className="h-full" />
            <SupportedPlatform platform={config.web} label="Web" />

            <LemonDivider vertical className="h-full" />
            <SupportedPlatform platform={config.android} label="Android" />

            <LemonDivider vertical className="h-full" />
            <SupportedPlatform platform={config.ios} label="iOS" />

            <LemonDivider vertical className="h-full" />
            <SupportedPlatform platform={config.reactNative} label="React Native" />

            <LemonDivider vertical className="h-full" />
            <SupportedPlatform platform={config.flutter} label="Flutter" />
        </div>
    )
})
