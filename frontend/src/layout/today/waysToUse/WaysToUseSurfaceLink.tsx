import { useActions } from 'kea'
import { ReactNode } from 'react'

import { IconArrowRight, IconExternal } from '@posthog/icons'
import { Button } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'

import { WaysToUseSurface } from './waysToUse'
import { waysToUseLogic } from './waysToUseLogic'

export interface WaysToUseSurfaceLinkProps {
    surface: WaysToUseSurface
    to: string
    external?: boolean
    children: ReactNode
}

export function WaysToUseSurfaceLink({ surface, to, external, children }: WaysToUseSurfaceLinkProps): JSX.Element {
    const { closeWaysToUse, trackWaysToUseClick } = useActions(waysToUseLogic)
    const Icon = external ? IconExternal : IconArrowRight

    return (
        <Button
            size="sm"
            variant="outline"
            nativeButton={false}
            role="link"
            className="after:absolute after:inset-0 after:rounded-lg active:translate-none"
            render={
                <LinkPrimitive
                    to={to}
                    target={external ? '_blank' : undefined}
                    onClick={() => (external ? trackWaysToUseClick(surface) : closeWaysToUse('surface_link', surface))}
                />
            }
            data-attr={`today-ways-to-use-${surface}`}
        >
            {children}
            <Icon className="transition-transform duration-200 ease-out group-has-[a:hover]/card:translate-x-0.5 motion-reduce:transition-none" />
        </Button>
    )
}
