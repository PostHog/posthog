import { ReactNode } from 'react'

import { IconArrowRight, IconExternal } from '@posthog/icons'
import { Button } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'

import { WaysToUseSurface } from './waysToUse'

export interface WaysToUseSurfaceLinkProps {
    surface: WaysToUseSurface
    to: string
    opensNewTab: boolean
    onClick: (surface: WaysToUseSurface, opensNewTab: boolean) => void
    children: ReactNode
}

export function WaysToUseSurfaceLink({
    surface,
    to,
    opensNewTab,
    onClick,
    children,
}: WaysToUseSurfaceLinkProps): JSX.Element {
    return (
        <Button
            size="sm"
            variant="outline"
            nativeButton={false}
            role="link"
            className="after:absolute after:inset-0 after:rounded-lg"
            render={
                <LinkPrimitive
                    to={to}
                    target={opensNewTab ? '_blank' : undefined}
                    onClick={() => onClick(surface, opensNewTab)}
                />
            }
            data-attr={`today-ways-to-use-${surface}`}
        >
            {children}
            {opensNewTab ? (
                <>
                    <IconExternal className="transition-transform duration-200 ease-out group-has-[a:hover]/card:translate-x-px group-has-[a:hover]/card:-translate-y-px motion-reduce:transition-none" />
                    <span className="sr-only">Opens in a new tab</span>
                </>
            ) : (
                <IconArrowRight className="transition-transform duration-200 ease-out group-has-[a:hover]/card:translate-x-0.5 motion-reduce:transition-none" />
            )}
        </Button>
    )
}
