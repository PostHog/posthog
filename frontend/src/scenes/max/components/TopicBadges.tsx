import { IconCode } from '@posthog/icons'
import { LemonButton, LemonTag } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'

import { iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'
import { FileSystemIconType } from '~/queries/schema/schema-general'

import { SelfDrivingIntroModal } from 'products/signals/frontend/inbox/components/onboarding/SelfDrivingIntroModal'

import { SuggestionTopic, TopicSuggestion } from '../suggestionTopics'
import { SuggestionCard } from './SuggestionCard'
import { useCodeBadge } from './useCodeBadge'

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
    const codeBadge = useCodeBadge()

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
                    aria-pressed={selectedKey === topic.key}
                    icon={badgeIcon(topic)}
                    onClick={() => onSelect(selectedKey === topic.key ? null : topic.key)}
                    data-attr={`capability-badge-${topic.key}`}
                >
                    {topic.label}
                </LemonButton>
            ))}

            {codeBadge.visible && (
                <>
                    <LemonButton
                        size="small"
                        type="secondary"
                        onClick={codeBadge.openIntro}
                        icon={<IconCode />}
                        data-attr="capability-badge-code"
                    >
                        <span className="flex items-center gap-1.5">
                            {codeBadge.label}
                            <LemonTag type="warning" size="small">
                                Beta
                            </LemonTag>
                        </span>
                    </LemonButton>

                    <SelfDrivingIntroModal isOpen={codeBadge.introOpen} onClose={codeBadge.closeIntro} />
                </>
            )}
        </div>
    )
}

export interface TopicSuggestionsProps {
    topic: SuggestionTopic
    /**
     * Run the suggestion. `maxLogic` owns the typewriter that writes it into the composer, so a send
     * that lands mid-animation still carries the whole suggestion.
     */
    onRun: (suggestion: TopicSuggestion) => void
    className?: string
}

/**
 * The suggestion cards for a selected topic. Fills its parent's baseline height (`h-full`).
 */
export function TopicSuggestions({ topic, onRun, className }: TopicSuggestionsProps): JSX.Element {
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
                            onClick={() => onRun(suggestion)}
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
                        onClick={() => onRun(suggestion)}
                        data-attr={`capability-suggestion-${topic.key}`}
                    />
                )
            })}
        </div>
    )
}
