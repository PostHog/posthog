import { useRef } from 'react'

import { IconExternal } from '@posthog/icons'
import { Tooltip } from '@posthog/lemon-ui'

import useIsHovering from 'lib/hooks/useIsHovering'
import { Link } from 'lib/lemon-ui/Link'
import { IconGithub } from 'lib/lemon-ui/icons'

import { SourceData } from './framesCodeSourceLogic'

const PROVIDER_ICON_MAP: Record<string, React.ComponentType<{ className?: string }>> = {
    github: IconGithub,
}

export function GitProviderFileLink({ sourceData }: { sourceData: SourceData }): JSX.Element {
    const ref = useRef<HTMLDivElement>(null)
    const isHovering = useIsHovering(ref)

    const ProviderIcon = sourceData.provider ? PROVIDER_ICON_MAP[sourceData.provider] : null
    const Icon = ProviderIcon || IconExternal

    return (
        <Tooltip title="View source" placement="top">
            <Link to={sourceData.url!} target="_blank" ref={ref} className="inline-flex items-center">
                <Icon className="w-3.5 h-3.5" color={isHovering ? 'red' : 'gray'} />
            </Link>
        </Tooltip>
    )
}
