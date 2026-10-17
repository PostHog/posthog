import { useActions } from 'kea'
import { ReactNode } from 'react'

import { IconArrowRight } from '@posthog/icons'
import { Button } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'

import { WaysToUseSurface } from './waysToUse'
import { waysToUseLogic } from './waysToUseLogic'

export interface WaysToUseSurfaceLinkProps {
    surface: WaysToUseSurface
    to: string
    children: ReactNode
}

export function WaysToUseSurfaceLink({ surface, to, children }: WaysToUseSurfaceLinkProps): JSX.Element {
    const { closeWaysToUse } = useActions(waysToUseLogic)

    return (
        <Button
            size="sm"
            variant="outline"
            nativeButton={false}
            role="link"
            className="after:absolute after:inset-0 after:rounded-lg active:translate-none"
            render={<LinkPrimitive to={to} onClick={() => closeWaysToUse('surface_link', surface)} />}
            data-attr={`today-ways-to-use-${surface}`}
        >
            {children}
            <IconArrowRight className="transition-transform duration-200 ease-out group-has-[a:hover]/card:translate-x-0.5 motion-reduce:transition-none" />
        </Button>
    )
}
