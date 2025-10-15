import { useRef } from 'react'

import { IconExternal } from '@posthog/icons'
import { Tooltip } from '@posthog/lemon-ui'

import useIsHovering from 'lib/hooks/useIsHovering'
import { Link } from 'lib/lemon-ui/Link'

export function GitProviderFileLink({ url, className }: { url: string; className?: string }): JSX.Element {
    const ref = useRef<HTMLDivElement>(null)
    const isHovering = useIsHovering(ref)

    return (
        <Tooltip title="View source" placement="top">
            <Link to={url} target="_blank" ref={ref}>
                <IconExternal className={className} color={isHovering ? 'red' : 'gray'} />
            </Link>
        </Tooltip>
    )
}
