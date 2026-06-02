import { IconBox } from '@posthog/icons'
import { Link, Tooltip } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'

import { symbolSetConfigUrl } from '../utils'

export function SymbolSetLink({
    symbolSetRef,
    resolved,
    className,
}: {
    symbolSetRef: string
    // Whether the frame resolved against this symbol set. Drives the tooltip copy (matched vs. expected).
    resolved: boolean
    className?: string
}): JSX.Element {
    return (
        <Tooltip
            title={
                resolved
                    ? 'This frame was symbolicated using this symbol set. Open it in configuration.'
                    : 'Expected symbol set for this frame. Open it in configuration to check whether a source map was uploaded.'
            }
        >
            <Link
                to={symbolSetConfigUrl(symbolSetRef)}
                className={cn('inline-flex items-center gap-1 max-w-full', className)}
            >
                <IconBox className="shrink-0" />
                <span className="font-mono text-xs truncate" title={symbolSetRef}>
                    {symbolSetRef}
                </span>
            </Link>
        </Tooltip>
    )
}
