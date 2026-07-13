import { useEffect, useRef } from 'react'

import { IconCode } from '@posthog/icons'
import { LemonButton, LemonTag } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { cn } from 'lib/utils/css-classes'

import { iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'
import { FileSystemIconType } from '~/queries/schema/schema-general'

import { CODE_CAPABILITY, Capability, CapabilitySuggestion } from '../maxCapabilities'
import { nextTypingDelayMs } from '../utils/typing'

// Colors the product icons (via iconForType's ProductIconWrapper). Applied inside the components so
// they look identical on every surface, not only where an ancestor happens to set it (e.g. /home).
const COLORFUL_ICONS = 'group/colorful-product-icons colorful-product-icons-true'

/**
 * Height of the suggestion-cards / recents-grid swap area. Set once on the outer container by each
 * surface; the cards and the homepage recents grid both fill it with `h-full`, so the two can never
 * differ and swapping between them (or between capabilities) never shifts layout.
 */
export const CAPABILITY_CARDS_HEIGHT_PX = 184

function badgeIcon(capability: Capability): JSX.Element {
    return capability.icon ?? iconForType(capability.iconType)
}

export interface CapabilityBadgesProps {
    capabilities: Capability[]
    selectedKey: string | null
    onSelect: (key: string | null) => void
    className?: string
}

/** Row of PostHog AI capability badges (+ the Code beta badge). Selection is owned by the parent. */
export function CapabilityBadges({
    capabilities,
    selectedKey,
    onSelect,
    className,
}: CapabilityBadgesProps): JSX.Element | null {
    const isProductAutonomyEnabled = useFeatureFlag('PRODUCT_AUTONOMY')

    if (!capabilities.length) {
        return null
    }

    return (
        <div
            className={cn(
                'flex flex-wrap items-center justify-center gap-1.5 max-w-[500px] px-3',
                COLORFUL_ICONS,
                className
            )}
        >
            {capabilities.map((capability) => (
                <LemonButton
                    key={capability.key}
                    size="small"
                    type="secondary"
                    active={selectedKey === capability.key}
                    icon={badgeIcon(capability)}
                    onClick={() => onSelect(selectedKey === capability.key ? null : capability.key)}
                    data-attr={`capability-badge-${capability.key}`}
                >
                    {capability.label}
                </LemonButton>
            ))}

            {isProductAutonomyEnabled && (
                <LemonButton
                    size="small"
                    type="secondary"
                    to={CODE_CAPABILITY.to}
                    icon={<IconCode />}
                    data-attr="capability-badge-code"
                >
                    <span className="flex items-center gap-1.5">
                        {CODE_CAPABILITY.label}
                        <LemonTag type="warning" size="small">
                            Beta
                        </LemonTag>
                    </span>
                </LemonButton>
            )}
        </div>
    )
}

export interface CapabilitySuggestionsProps {
    capability: Capability
    /** Called per keystroke of the typewriter animation, and once more with the full prompt. */
    onType: (text: string) => void
    /** Send the fully typed prompt to PostHog AI. */
    onSubmit: (text: string) => void
    /** Fired after a fill-in prompt is typed in — the parent shows `hint` as a postfix cue + focuses. */
    onFillIn: (hint: string) => void
    className?: string
}

/**
 * The 4 suggestion cards for a selected capability. Fills its parent's height (`h-full`) — the
 * parent sets the fixed height (see `CAPABILITY_CARDS_HEIGHT_PX`), and the 4 cards split it evenly.
 */
export function CapabilitySuggestions({
    capability,
    onType,
    onSubmit,
    onFillIn,
    className,
}: CapabilitySuggestionsProps): JSX.Element {
    // Cancels an in-flight typewriter animation (new click, or unmount).
    const cancelTypingRef = useRef<(() => void) | null>(null)
    useEffect(() => () => cancelTypingRef.current?.(), [])

    // Type the prompt at a human pace, then either send it, or — for a fill-in prompt — add a
    // trailing space and hand the hint to the parent so it can show the postfix cue.
    const runSuggestion = (suggestion: CapabilitySuggestion): void => {
        cancelTypingRef.current?.()
        const { content, requiresUserInput, hint } = suggestion
        let cancelled = false
        let timer: ReturnType<typeof setTimeout> | undefined
        cancelTypingRef.current = () => {
            cancelled = true
            if (timer) {
                clearTimeout(timer)
            }
        }
        const finish = (): void => {
            if (cancelled) {
                return
            }
            if (requiresUserInput) {
                onType(`${content} `)
                onFillIn(hint ?? 'the details')
            } else {
                onSubmit(content)
            }
        }
        const typeTo = (i: number): void => {
            if (cancelled) {
                return
            }
            onType(content.slice(0, i))
            if (i >= content.length) {
                timer = setTimeout(finish, 250)
                return
            }
            timer = setTimeout(() => typeTo(i + 1), nextTypingDelayMs(content[i - 1] ?? '', content[i]))
        }
        typeTo(1)
    }

    // Docs-style: a plain question list (like production's Docs suggestions), reading as an
    // explanation rather than an action. Card-style: icon + bold title + description.
    const isDocs = capability.variant === 'docs'
    return (
        <div
            className={cn('w-full h-full px-3 flex flex-col gap-px', COLORFUL_ICONS, className)}
            data-attr="capability-suggestions"
        >
            {capability.suggestions.map((suggestion) => {
                const iconType: FileSystemIconType = suggestion.iconType ?? capability.iconType
                return (
                    <LemonButton
                        key={suggestion.content}
                        className="flex-1 min-h-0"
                        fullWidth
                        type={isDocs ? 'tertiary' : undefined}
                        onClick={() => runSuggestion(suggestion)}
                        icon={isDocs ? undefined : iconForType(iconType)}
                        data-attr={`capability-suggestion-${capability.key}`}
                    >
                        {isDocs ? (
                            <span className="text-sm font-normal text-left truncate w-full">{suggestion.content}</span>
                        ) : (
                            <div className="flex flex-col text-left leading-tight min-w-0">
                                <span className="text-sm font-semibold truncate">{suggestion.title}</span>
                                <span className="text-xs text-secondary font-normal truncate">
                                    {suggestion.description}
                                </span>
                            </div>
                        )}
                    </LemonButton>
                )
            })}
        </div>
    )
}
