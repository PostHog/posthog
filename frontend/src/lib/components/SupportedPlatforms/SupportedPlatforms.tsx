import { memo } from 'react'

import { IconCheck, IconInfo, IconX } from '@posthog/icons'
import { Tooltip } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'
import { isObject } from 'lib/utils/guards'

import { PlatformSupport, PlatformSupportConfig } from './types'

type SupportedPlatformProps = {
    config: PlatformSupportConfig
}

const PLATFORM_LABELS: Record<string, string> = {
    web: 'Web',
    android: 'Android',
    ios: 'iOS',
    reactNative: 'React Native',
    flutter: 'Flutter',
}

function SupportedPlatform({ label, platform }: { label: string; platform: PlatformSupport | undefined }): JSX.Element {
    const supportedSinceVersion = isObject(platform) && typeof platform?.version === 'string' ? platform.version : false
    const note = isObject(platform) ? platform.note : undefined

    const node = (
        <span className={cn('flex items-center gap-0.5', { 'cursor-help': note && supportedSinceVersion })}>
            {note ? (
                <IconInfo className="text-secondary" />
            ) : supportedSinceVersion ? (
                <IconCheck className="text-success" />
            ) : (
                <IconX className="text-warning" />
            )}
            {label}
        </span>
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
    const platforms = Object.keys(config) as Array<keyof PlatformSupportConfig>
    if (platforms.length === 0) {
        return null
    }

    return (
        <div className="text-xs font-normal text-secondary inline-flex flex-row flex-wrap items-center gap-x-2 w-fit">
            <Tooltip delayMs={200} title="We support lots of platforms! But not every feature works everywhere (yet)">
                <span className="cursor-help">Supported platforms:</span>
            </Tooltip>
            {platforms.map((platform) => (
                <SupportedPlatform
                    key={platform}
                    platform={config[platform]}
                    label={PLATFORM_LABELS[platform] || platform}
                />
            ))}
        </div>
    )
})
