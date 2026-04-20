import { memo } from 'react'

import { IconCheck, IconInfo, IconX } from '@posthog/icons'
import { Tooltip } from '@posthog/lemon-ui'

import { isObject } from 'lib/utils'
import { cn } from 'lib/utils/css-classes'

import { PlatformSupportConfig } from './types'

const PLATFORM_LABELS: Record<string, string> = {
    web: 'Web',
    android: 'Android',
    ios: 'iOS',
    reactNative: 'React Native',
    flutter: 'Flutter',
}

export const SupportedPlatforms = memo(function SupportedPlatforms({
    config,
}: {
    config: PlatformSupportConfig
}): JSX.Element | null {
    const platforms = Object.keys(config) as Array<keyof PlatformSupportConfig>
    if (platforms.length === 0) {
        return null
    }

    return (
        <div className="text-xs inline-flex flex-wrap items-center border rounded overflow-hidden">
            {platforms.map((platform) => {
                const value = config[platform]
                const supported = isObject(value) && typeof value.version === 'string'
                const note = isObject(value) ? value.note : undefined
                const version = isObject(value) ? value.version : undefined

                const tooltipContent =
                    version || note ? (
                        <div>
                            {version && <div>Since version {version}</div>}
                            {note && <div>{note}</div>}
                        </div>
                    ) : undefined

                return (
                    <Tooltip key={platform} delayMs={200} title={tooltipContent}>
                        <div
                            className={cn(
                                'px-1.5 py-0.5 flex items-center gap-1 whitespace-nowrap border-l first:border-l-0',
                                supported ? 'bg-fill-success-highlight' : 'bg-fill-warning-highlight'
                            )}
                        >
                            {note ? (
                                <IconInfo className="size-3" />
                            ) : supported ? (
                                <IconCheck className="size-3" />
                            ) : (
                                <IconX className="size-3" />
                            )}
                            {PLATFORM_LABELS[platform] || platform}
                        </div>
                    </Tooltip>
                )
            })}
        </div>
    )
})
