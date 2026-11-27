import { IconExternal, IconInfo } from '@posthog/icons'
import {
    Badge,
    Button,
    Item,
    ItemActions,
    ItemContent,
    ItemDescription,
    ItemMedia,
    ItemTitle,
    Text,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
} from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import type { Suggestion } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/setupPlanLogic'

import { QuillSuggestionIcon } from './QuillSuggestionIcon'
import { CAPABILITY_COPY } from './ReadinessHeader'

export function QuillSuggestionRow({
    suggestion,
    isDismissed,
    isApplying,
    ctaLabel,
    ctaDisabledReason,
    sectionCtaLabel,
    urlFixSnippet,
    onReview,
    onSectionCta,
    onCopyUrlFix,
    onDismiss,
    onRestore,
}: {
    suggestion: Suggestion
    isDismissed: boolean
    isApplying: boolean
    ctaLabel: string | null
    ctaDisabledReason: string | null | undefined
    sectionCtaLabel: string | null
    /** `null` when there's no URL fix to recommend, an empty string when there is but
     * no UTM values to spell out. */
    urlFixSnippet: string | null
    onReview: () => void
    onSectionCta: () => void
    onCopyUrlFix: () => void
    onDismiss: () => void
    onRestore: () => void
}): JSX.Element {
    return (
        <Item variant="outline" className="items-start">
            <ItemMedia>
                <QuillSuggestionIcon suggestion={suggestion} />
            </ItemMedia>

            <ItemContent className="min-w-0 basis-64">
                <ItemTitle className="flex-wrap">
                    <span>{suggestion.title}</span>
                    {suggestion.source === 'ai' && (
                        <Tooltip>
                            <TooltipTrigger render={<Badge variant="info" tabIndex={0} />}>AI</TooltipTrigger>
                            <TooltipContent>
                                Suggested by AI from your data. Review the evidence before applying.
                            </TooltipContent>
                        </Tooltip>
                    )}
                </ItemTitle>

                <ItemDescription>{suggestion.evidence}</ItemDescription>

                {suggestion.unlocks.length > 0 && (
                    <div className="flex flex-wrap items-center gap-1">
                        <Text size="xs" variant="muted" render={<span />}>
                            Unlocks
                        </Text>
                        <Tooltip>
                            <TooltipTrigger delay={0} render={<Button size="icon-xs" aria-label="About unlocks" />}>
                                <IconInfo />
                            </TooltipTrigger>
                            <TooltipContent>
                                The metrics this fix makes available. They stay empty or wrong until it's done.
                            </TooltipContent>
                        </Tooltip>
                        {suggestion.unlocks.map((capability) => {
                            const copy = CAPABILITY_COPY[capability]
                            return copy?.what ? (
                                <Tooltip key={capability}>
                                    <TooltipTrigger render={<Badge tabIndex={0} />}>{copy.label}</TooltipTrigger>
                                    <TooltipContent>{copy.what}</TooltipContent>
                                </Tooltip>
                            ) : (
                                <Badge key={capability}>{copy?.label ?? capability}</Badge>
                            )
                        })}
                    </div>
                )}

                {urlFixSnippet === '' && (
                    <Text size="xs" variant="muted" render={<span className="m-0" />}>
                        Better fix: tag the ad URLs in the platform so the UTM values match.
                    </Text>
                )}
                {urlFixSnippet && (
                    <div className="flex flex-wrap items-center gap-2">
                        <Text size="xs" variant="muted" render={<span className="m-0" />}>
                            Better fix — tag the ad URLs with
                        </Text>
                        <code className="font-mono text-xs break-all text-muted-foreground">{urlFixSnippet}</code>
                        <Button size="xs" onClick={onCopyUrlFix}>
                            Copy
                        </Button>
                    </div>
                )}
            </ItemContent>

            <ItemActions className="ml-auto flex-wrap">
                {ctaLabel && (
                    <Button
                        variant="primary"
                        loading={isApplying}
                        disabledReason={ctaDisabledReason}
                        onClick={onReview}
                    >
                        {ctaLabel}
                    </Button>
                )}
                {!ctaLabel && suggestion.deep_link && (
                    <Button
                        variant="outline"
                        nativeButton={false}
                        render={<LinkPrimitive to={suggestion.deep_link} target="_blank" />}
                    >
                        Open source
                        <IconExternal />
                    </Button>
                )}
                {!suggestion.deep_link && sectionCtaLabel && (
                    <Button variant="outline" onClick={onSectionCta}>
                        {sectionCtaLabel}
                    </Button>
                )}
                {isDismissed ? (
                    <Button variant="outline" tooltip="Put this back in the list" onClick={onRestore}>
                        Restore
                    </Button>
                ) : (
                    <Button
                        variant="outline"
                        tooltip="Hide this — it stays hidden across rescans until you restore it, and nothing is fixed"
                        onClick={onDismiss}
                    >
                        Dismiss
                    </Button>
                )}
            </ItemActions>
        </Item>
    )
}
