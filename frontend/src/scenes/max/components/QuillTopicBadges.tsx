import { IconCode } from '@posthog/icons'
import { Badge, Button, Card, CardGroup, Text, cn } from '@posthog/quill'

import { iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'
import { FileSystemIconType } from '~/queries/schema/schema-general'

import { SelfDrivingIntroModal } from 'products/signals/frontend/inbox/components/onboarding/SelfDrivingIntroModal'

import { SuggestionTopic } from '../suggestionTopics'
import { COLORFUL_ICONS, type TopicBadgesProps, type TopicSuggestionsProps } from './TopicBadges'
import { useCodeBadge } from './useCodeBadge'

function badgeIcon(topic: SuggestionTopic): JSX.Element {
    return topic.icon ?? iconForType(topic.iconType)
}

// pinned: the `capability-*` data-attr values below predate the topic naming and are frozen;
// autocapture dashboards depend on them, so the rename stops at code symbols.

/** The topic badge row in the quill skin: outline buttons that press in when selected. */
export function QuillTopicBadges({ topics, selectedKey, onSelect, className }: TopicBadgesProps): JSX.Element | null {
    const codeBadge = useCodeBadge()

    if (!topics.length) {
        return null
    }

    return (
        <div
            data-quill
            className={cn(
                'flex flex-wrap items-center justify-center gap-1.5 max-w-[500px] px-3 pt-[2px]',
                COLORFUL_ICONS,
                className
            )}
        >
            {topics.map((topic) => (
                <Button
                    key={topic.key}
                    size="sm"
                    variant="outline"
                    className={cn(selectedKey === topic.key && 'bg-fill-selected')}
                    aria-pressed={selectedKey === topic.key}
                    onClick={() => onSelect(selectedKey === topic.key ? null : topic.key)}
                    data-attr={`capability-badge-${topic.key}`}
                >
                    {badgeIcon(topic)}
                    {topic.label}
                </Button>
            ))}

            {codeBadge.visible && (
                <>
                    <Button size="sm" variant="outline" onClick={codeBadge.openIntro} data-attr="capability-badge-code">
                        <IconCode />
                        {codeBadge.label}
                        <Badge variant="warning">Beta</Badge>
                    </Button>

                    <SelfDrivingIntroModal isOpen={codeBadge.introOpen} onClose={codeBadge.closeIntro} />
                </>
            )}
        </div>
    )
}

/** The suggestion rows for a selected topic in the quill skin: one card per suggestion, each a full-width button. */
export function QuillTopicSuggestions({ topic, onRun, className }: TopicSuggestionsProps): JSX.Element {
    const isDocs = topic.variant === 'docs'
    return (
        <CardGroup
            size="sm"
            data-quill
            className={cn('w-full px-3', COLORFUL_ICONS, className)}
            data-attr="capability-suggestions"
        >
            {topic.suggestions.map((suggestion) => {
                const iconType: FileSystemIconType = suggestion.iconType ?? topic.iconType
                return (
                    <Card key={suggestion.content} size="sm" className="p-0">
                        <button
                            type="button"
                            className="flex w-full items-center gap-2 px-3 py-2 text-left hover:bg-fill-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                            onClick={() => onRun(suggestion)}
                            data-attr={`capability-suggestion-${topic.key}`}
                        >
                            {!isDocs && <span className="flex shrink-0 text-base">{iconForType(iconType)}</span>}
                            <span className="flex min-w-0 flex-col leading-tight">
                                <Text
                                    size="sm"
                                    weight={isDocs ? 'normal' : 'semibold'}
                                    className="m-0 truncate"
                                    render={<span />}
                                >
                                    {isDocs ? suggestion.content : (suggestion.title ?? suggestion.content)}
                                </Text>
                                {!isDocs && suggestion.description && (
                                    <Text size="xs" variant="muted" className="m-0 truncate" render={<span />}>
                                        {suggestion.description}
                                    </Text>
                                )}
                            </span>
                        </button>
                    </Card>
                )
            })}
        </CardGroup>
    )
}
