import { IconInfo, IconWarning } from '@posthog/icons'
import { Dot, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import type { Suggestion } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/setupPlanLogic'

import { SEVERITY_LABEL, usePlatformLogo } from './SuggestionIcon'

const SEVERITY_DOT = {
    error: 'destructive',
    warning: 'warning',
    info: 'default',
} as const

export function QuillSuggestionIcon({ suggestion }: { suggestion: Suggestion }): JSX.Element {
    const logo = usePlatformLogo(suggestion.integration)
    const label = suggestion.integration
        ? `${suggestion.integration} · ${SEVERITY_LABEL[suggestion.severity]}`
        : SEVERITY_LABEL[suggestion.severity]

    return (
        <Tooltip>
            <TooltipTrigger
                render={
                    <span
                        className="relative flex size-7.5 shrink-0 cursor-help items-center justify-center"
                        data-attr="suggestion-icon"
                        tabIndex={0}
                        aria-label={label}
                    />
                }
            >
                {logo ??
                    (suggestion.severity === 'info' ? (
                        <IconInfo className="text-lg text-muted-foreground" />
                    ) : (
                        <IconWarning
                            className={
                                suggestion.severity === 'error'
                                    ? 'text-lg text-destructive-foreground'
                                    : 'text-lg text-warning-foreground'
                            }
                        />
                    ))}
                {logo && (
                    <Dot variant={SEVERITY_DOT[suggestion.severity]} className="absolute -right-0.5 -bottom-0.5" />
                )}
            </TooltipTrigger>
            <TooltipContent>{label}</TooltipContent>
        </Tooltip>
    )
}
