import { useEffect, useRef } from 'react'

import { IconCode } from '@posthog/icons'
import { LemonButton, LemonTag } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { cn } from 'lib/utils/css-classes'

import { iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'
import { FileSystemIconType } from '~/queries/schema/schema-general'

import { CODE_BADGE, SuggestionTopic, TopicSuggestion } from '../suggestionTopics'
import { nextTypingDelayMs } from '../utils/typing'
import { SuggestionCard } from './SuggestionCard'

// Colors the product icons (via iconForType's ProductIconWrapper). Applied inside the components so
// they look identical on every surface, not only where an ancestor happens to set it (e.g. /home).
export const COLORFUL_ICONS = 'group/colorful-product-icons colorful-product-icons-true'

/**
 * Baseline height of the suggestion-cards / recents-grid swap area. Each surface can grow beyond it
 * when its content needs more space.
 */
export const SUGGESTION_CARDS_HEIGHT_PX = 184

function badgeIcon(topic: SuggestionTopic): JSX.Element {
    return topic.icon ?? iconForType(topic.iconType)
}

export interface TopicBadgesProps {
    topics: SuggestionTopic[]
    selectedKey: string | null
    onSelect: (key: string | null) => void
    className?: string
}

// pinned: the `capability-*` data-attr values below predate the topic naming and are frozen;
// autocapture dashboards depend on them, so the rename stops at code symbols.

/** Row of PostHog AI topic badges (+ the Desktop beta badge). Selection is owned by the parent. */
export function TopicBadges({ topics, selectedKey, onSelect, className }: TopicBadgesProps): JSX.Element | null {
    const isProductAutonomyEnabled = useFeatureFlag('PRODUCT_AUTONOMY')

    if (!topics.length) {
        return null
    }

    return (
        <div
            className={cn(
                'flex flex-wrap items-center justify-center gap-1.5 max-w-[500px] px-3 pt-[2px]',
                COLORFUL_ICONS,
                className
            )}
        >
            {topics.map((topic) => (
                <LemonButton
                    key={topic.key}
                    size="small"
                    type="secondary"
                    active={selectedKey === topic.key}
                    icon={badgeIcon(topic)}
                    onClick={() => onSelect(selectedKey === topic.key ? null : topic.key)}
                    data-attr={`capability-badge-${topic.key}`}
                >
                    {topic.label}
                </LemonButton>
            ))}

            {isProductAutonomyEnabled && (
                <LemonButton
                    size="small"
                    type="secondary"
                    to={CODE_BADGE.to}
                    icon={<IconCode />}
                    data-attr="capability-badge-code"
                >
                    <span className="flex items-center gap-1.5">
                        {CODE_BADGE.label}
                        <LemonTag type="warning" size="small">
                            Beta
                        </LemonTag>
                    </span>
                </LemonButton>
            )}
        </div>
    )
}

export interface TopicSuggestionsProps {
    topic: SuggestionTopic
    /** Called per keystroke of the typewriter animation, and once more with the full prompt. */
    onType: (text: string) => void
    /** Send the fully typed prompt to PostHog AI. */
    onSubmit: (text: string) => void
    /** Fired after a fill-in prompt is typed in — the parent shows `hint` as a postfix cue + focuses. */
    onFillIn: (hint: string) => void
    className?: string
}

/**
 * The suggestion cards for a selected topic. Fills its parent's baseline height (`h-full`).
 */
export function TopicSuggestions({ topic, onType, onSubmit, onFillIn, className }: TopicSuggestionsProps): JSX.Element {
    // Cancels an in-flight typewriter animation (new click, or unmount).
    const cancelTypingRef = useRef<(() => void) | null>(null)
    useEffect(() => () => cancelTypingRef.current?.(), [])

    // Type the prompt at a human pace, then either send it, or — for a fill-in prompt — add a
    // trailing space and hand the hint to the parent so it can show the postfix cue.
    const runSuggestion = (suggestion: TopicSuggestion): void => {
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
    const isDocs = topic.variant === 'docs'
    return (
        <div
            className={cn('w-full h-full px-3 flex flex-col gap-px', COLORFUL_ICONS, className)}
            data-attr="capability-suggestions"
        >
            {topic.suggestions.map((suggestion) => {
                const iconType: FileSystemIconType = suggestion.iconType ?? topic.iconType
                if (isDocs) {
                    return (
                        <LemonButton
                            key={suggestion.content}
                            className="flex-1 min-h-0"
                            fullWidth
                            type="tertiary"
                            onClick={() => runSuggestion(suggestion)}
                            data-attr={`capability-suggestion-${topic.key}`}
                        >
                            <span className="text-sm font-normal text-left truncate w-full">{suggestion.content}</span>
                        </LemonButton>
                    )
                }
                return (
                    <SuggestionCard
                        key={suggestion.content}
                        className="flex-1 min-h-0"
                        title={suggestion.title ?? suggestion.content}
                        description={suggestion.description}
                        icon={iconForType(iconType)}
                        onClick={() => runSuggestion(suggestion)}
                        data-attr={`capability-suggestion-${topic.key}`}
                    />
                )
            })}
        </div>
    )
}
