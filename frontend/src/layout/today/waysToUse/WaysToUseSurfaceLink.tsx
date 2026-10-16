import { ReactNode } from 'react'

import { IconArrowRight } from '@posthog/icons'
import { Button } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'

import { WaysToUseSurface } from './waysToUse'

export interface WaysToUseSurfaceLinkProps {
    surface: WaysToUseSurface
    to: string
    onClick: (surface: WaysToUseSurface) => void
    children: ReactNode
}

export function WaysToUseSurfaceLink({ surface, to, onClick, children }: WaysToUseSurfaceLinkProps): JSX.Element {
    return (
        <Button
            size="sm"
            variant="outline"
            nativeButton={false}
            role="link"
            className="after:absolute after:inset-0 after:rounded-lg"
            render={<LinkPrimitive to={to} onClick={() => onClick(surface)} />}
            data-attr={`today-ways-to-use-${surface}`}
        >
            {children}
            <IconArrowRight className="transition-transform duration-200 ease-out group-has-[a:hover]/card:translate-x-0.5 motion-reduce:transition-none" />
        </Button>
    )
}
