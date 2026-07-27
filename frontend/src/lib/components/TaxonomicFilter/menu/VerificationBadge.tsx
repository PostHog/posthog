/**
 * Verification badge for taxonomic filter rows + preview pane.
 *
 * Two mutually-exclusive states (core defs can't be team-verified — see
 * `DefinitionPopoverContents`'s `allowVerification`):
 *   - `core`     — a built-in PostHog definition (`isCoreFilter`). Badge
 *                  reads "By PostHog" with the logomark.
 *   - `verified` — a custom definition a team explicitly marked verified
 *                  (`item.verified`). Badge reads "Verified".
 */
import { IconBadge, IconLogomark } from '@posthog/icons'
import { Badge, cn, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { isCoreFilter } from '~/taxonomy/helpers'

import { MenuFilterEntry } from './types'

type Verification = { kind: 'core' } | { kind: 'verified' }

export function getVerification(entry: MenuFilterEntry): Verification | null {
    // Core PostHog definitions ($pageview, $browser, …) are inherently
    // verified — surfaced as "By PostHog" rather than a team flag.
    if (isCoreFilter(entry.name)) {
        return { kind: 'core' }
    }
    if ((entry.item as { verified?: boolean })?.verified) {
        return { kind: 'verified' }
    }
    return null
}

export function VerificationBadge({
    entry,
    className,
}: {
    entry: MenuFilterEntry
    className?: string
}): JSX.Element | null {
    const verification = getVerification(entry)
    if (!verification) {
        return null
    }
    const isCore = verification.kind === 'core'
    return (
        <Tooltip>
            {/* The trigger must render a host element (a `<span>`) so
                base-ui's ref + hover handlers actually attach — `Badge` is
                a plain function component (not `forwardRef`), so spreading
                the trigger's `ref` onto it gets dropped and the tooltip
                never anchors/opens. The Badge is plain visual content
                inside the trigger span. */}
            <TooltipTrigger
                delay={300}
                render={(triggerProps) => (
                    <span {...triggerProps} className={cn('inline-flex', className)}>
                        <Badge variant={isCore ? 'default' : 'success'} className="gap-1 shrink-0">
                            {isCore ? <IconLogomark className="size-3" /> : <IconBadge className="size-3" />}
                            {isCore ? 'PostHog' : 'Verified'}
                        </Badge>
                    </span>
                )}
            />
            <TooltipContent className="max-w-64 flex-col items-start">
                {isCore ? (
                    <>
                        <strong>Built into PostHog.</strong> A core definition PostHog ships, maintains, and documents.
                        Its name, type, and description are managed for you, so you don't need to verify it.
                    </>
                ) : (
                    <>
                        <strong>Verified by your team.</strong> Someone marked this definition as the right one to use.
                        Verified items are prioritized in filters so collaborators reach for them over similar,
                        unverified ones.
                    </>
                )}
            </TooltipContent>
        </Tooltip>
    )
}
