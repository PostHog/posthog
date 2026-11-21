import { IconShield, IconShieldEmpty, IconShieldExclamation } from '@posthog/icons'
import { Tooltip, TooltipContent, TooltipTrigger, cn } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'

import { IDENTITY_DOCS_URL, identityBadgeTooltip } from './identityBadgeText'

/** The icon-only identity badge, for dense rows such as the ticket list. */
export function QuillIdentityBadge({ verified }: { verified: boolean | null }): JSX.Element {
    const label = identityBadgeTooltip(verified)
    return (
        <Tooltip>
            <TooltipTrigger
                render={
                    <span
                        aria-label={label}
                        className={cn(
                            'inline-flex shrink-0',
                            verified
                                ? 'text-success-foreground'
                                : verified === false
                                  ? 'text-warning-foreground'
                                  : 'text-muted-foreground'
                        )}
                    />
                }
            >
                {verified ? <IconShield /> : verified === false ? <IconShieldExclamation /> : <IconShieldEmpty />}
            </TooltipTrigger>
            <TooltipContent className="max-w-80">
                <div className="flex flex-col items-start gap-1">
                    <span>{label}</span>
                    <LinkPrimitive
                        to={IDENTITY_DOCS_URL}
                        target="_blank"
                        className="text-primary-on-foreground underline"
                    >
                        Read the docs
                    </LinkPrimitive>
                </div>
            </TooltipContent>
        </Tooltip>
    )
}
