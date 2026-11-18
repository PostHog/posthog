import { IconCheck, IconInfo, IconX } from '@posthog/icons'
import { Badge, Text, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { PLATFORM_LABELS, platformSupportDetails } from './platformSupportDetails'
import { PlatformSupport, PlatformSupportConfig } from './types'

function QuillSupportedPlatform({
    label,
    platform,
}: {
    label: string
    platform: PlatformSupport | undefined
}): JSX.Element {
    const { supportedSinceVersion, note } = platformSupportDetails(platform)

    const badge = (
        <Badge variant={supportedSinceVersion ? 'success' : 'warning'}>
            {note ? <IconInfo /> : supportedSinceVersion ? <IconCheck /> : <IconX />}
            {label}
        </Badge>
    )

    if (!supportedSinceVersion && !note) {
        return badge
    }

    return (
        <Tooltip>
            <TooltipTrigger render={badge} />
            <TooltipContent>
                <div className="flex flex-col gap-1">
                    {supportedSinceVersion && <span>Since version {supportedSinceVersion}</span>}
                    {note && <span>{note}</span>}
                </div>
            </TooltipContent>
        </Tooltip>
    )
}

export function QuillSupportedPlatforms({ config }: { config: PlatformSupportConfig }): JSX.Element | null {
    const platforms = Object.keys(config) as Array<keyof PlatformSupportConfig>
    if (platforms.length === 0) {
        return null
    }

    return (
        <span className="inline-flex flex-wrap items-center gap-1 font-normal">
            <Tooltip>
                <TooltipTrigger
                    render={
                        <Text size="xs" variant="muted" className="m-0 cursor-help" render={<span />}>
                            Supported platforms:
                        </Text>
                    }
                />
                <TooltipContent>
                    We support lots of platforms! But not every feature works everywhere (yet)
                </TooltipContent>
            </Tooltip>
            {platforms.map((platform) => (
                <QuillSupportedPlatform
                    key={platform}
                    platform={config[platform]}
                    label={PLATFORM_LABELS[platform] || platform}
                />
            ))}
        </span>
    )
}
