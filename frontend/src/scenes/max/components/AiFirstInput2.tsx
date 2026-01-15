import { Autocomplete } from '@base-ui/react/autocomplete'
import { useActions, useValues } from 'kea'
import { useEffect, useMemo, useRef, useState } from 'react'

import {
    IconArrowRight,
    IconFlask,
    IconGraph,
    IconMessage,
    IconPieChart,
    IconRewindPlay,
    IconSparkles,
    IconToggle,
} from '@posthog/icons'

import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { cn } from 'lib/utils/css-classes'
import { newTabSceneLogic } from 'scenes/new-tab/newTabSceneLogic'

import { iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'
import { splitPath } from '~/layout/panel-layout/ProjectTree/utils'
import { FileSystemIconType } from '~/queries/schema/schema-general'

import { maxLogic } from '../maxLogic'
import { maxThreadLogic } from '../maxThreadLogic'

interface SuggestionItem {
    id: string
    label: string
    value: string
    description?: string
    icon?: JSX.Element
    type: 'ask-ai' | 'suggestion' | 'recent'
}

const AI_SUGGESTIONS: SuggestionItem[] = [
    {
        id: 's1',
        label: 'Show me user retention over the last 30 days',
        value: 'Show me user retention over the last 30 days',
        description: 'Product analytics',
        icon: <IconGraph />,
        type: 'suggestion',
    },
    {
        id: 's2',
        label: 'Which features have the highest adoption rate?',
        value: 'Which features have the highest adoption rate?',
        description: 'Feature flags',
        icon: <IconToggle />,
        type: 'suggestion',
    },
    {
        id: 's3',
        label: 'Create a funnel for our signup flow',
        value: 'Create a funnel for our signup flow',
        description: 'Product analytics',
        icon: <IconGraph />,
        type: 'suggestion',
    },
    {
        id: 's4',
        label: 'How many active users do we have this week?',
        value: 'How many active users do we have this week?',
        description: 'Web analytics',
        icon: <IconPieChart />,
        type: 'suggestion',
    },
    {
        id: 's5',
        label: 'What events are most correlated with conversion?',
        value: 'What events are most correlated with conversion?',
        description: 'Experiments',
        icon: <IconFlask />,
        type: 'suggestion',
    },
    {
        id: 's6',
        label: 'Create a survey to collect NPS scores',
        value: 'Create a survey to collect NPS scores',
        description: 'Surveys',
        icon: <IconMessage />,
        type: 'suggestion',
    },
    {
        id: 's7',
        label: 'Show me session recordings from frustrated users',
        value: 'Show me session recordings from frustrated users',
        description: 'Session replay',
        icon: <IconRewindPlay />,
        type: 'suggestion',
    },
]

export function AiFirstInput2(): JSX.Element {
    const { question } = useValues(maxLogic)
    const { setQuestion } = useActions(maxLogic)
    const { askMax } = useActions(maxThreadLogic)
    const { threadLoading, submissionDisabledReason } = useValues(maxThreadLogic)
    const inputRef = useRef<HTMLInputElement>(null)
    const [inputValue, setInputValue] = useState(question)
    const [isExpanded, setIsExpanded] = useState(false)

    const { recents } = useValues(newTabSceneLogic({ tabId: 'ai-first-input' }))

    const recentItems: SuggestionItem[] = useMemo(() => {
        return recents.results.slice(0, 5).map((item) => {
            const name = splitPath(item.path).pop() || item.path
            return {
                id: `recent-${item.path}`,
                label: name,
                value: name,
                description: item.type || 'Recent',
                icon: iconForType(item.type as FileSystemIconType),
                type: 'recent' as const,
            }
        })
    }, [recents.results])

    const items = useMemo(() => {
        // Hide all suggestions when input has any value
        if (inputValue.trim()) {
            return []
        }

        const result: SuggestionItem[] = []

        // Show suggestions only when input is empty
        result.push(...AI_SUGGESTIONS.slice(0, 4))

        // Add recents
        // if (recentItems.length > 0) {
        //     result.push(...recentItems)
        // }

        return result
    }, [inputValue, recentItems])

    useEffect(() => {
        setInputValue(question)
    }, [question])

    const handleValueChange = (value: string): void => {
        setInputValue(value)
        setQuestion(value)
        // Collapse when user clears input
        if (!value.trim()) {
            setIsExpanded(false)
        }
    }

    const handleItemSelect = (item: SuggestionItem): void => {
        if (item.type === 'ask-ai') {
            handleSubmit()
            return
        }

        setInputValue(item.value)
        setQuestion(item.value)
        setIsExpanded(true)
        inputRef.current?.focus()
    }

    const handleSubmit = (): void => {
        if (inputValue && !submissionDisabledReason && !threadLoading) {
            askMax(inputValue)
        }
    }

    return (
        <Autocomplete.Root
            open={true}
            value={inputValue}
            onValueChange={handleValueChange}
            items={items}
            itemToStringValue={(item: SuggestionItem) => item.value}
            mode="none"
            autoHighlight="always"
        >
            <div className="AiFirstInput2 relative w-full border border-primary rounded-lg overflow-hidden">
                <label
                    htmlFor="ai-first-input-2"
                    className={cn(
                        'flex items-center w-full text-sm outline-none relative bg-surface-primary text-primary gap-2 px-3 transition-all duration-300 ease-out',
                        isExpanded
                            ? 'border-secondary h-32 items-start pt-3 [--input-ring-size:2px] [--input-ring-color:#b62ad9] focus-within:ring-[length:var(--input-ring-size)] focus-within:ring-[color:var(--input-ring-color)]'
                            : 'border-primary h-12 hover:border-secondary focus-within:border-secondary'
                    )}
                >
                    <IconSparkles
                        className={cn(
                            'shrink-0 transition-all duration-300',
                            isExpanded ? 'size-5 text-[#b62ad9]' : 'size-4 text-secondary'
                        )}
                    />
                    <Autocomplete.Input
                        id="ai-first-input-2"
                        ref={inputRef}
                        placeholder="Ask a question"
                        onKeyDown={(e) => {
                            if (e.key === 'Enter' && !e.shiftKey) {
                                if (isExpanded || items.length === 0) {
                                    e.preventDefault()
                                    handleSubmit()
                                }
                            }
                            if (e.key === 'Escape' && isExpanded) {
                                setIsExpanded(false)
                            }
                        }}
                        className={cn(
                            'flex-1 bg-transparent outline-none placeholder:text-tertiary transition-all duration-300 [--input-ring-size:2px] [--input-ring-color:#b62ad9]'
                        )}
                    />
                    <ButtonPrimitive
                        iconOnly
                        onClick={handleSubmit}
                        className={cn(
                            'rounded-full shrink-0 transition-all duration-300',
                            '[--hover-bg-color:#b62ad9]',
                            '[--active-bg-color:transparent]',
                            inputValue.length > 0
                                ? 'opacity-100 [--base-bg-color:#b62ad9] [--active-bg-color:transparent]'
                                : 'opacity-50'
                        )}
                        variant="panel"
                    >
                        <IconArrowRight
                            className={cn(
                                'size-4 -rotate-90',
                                inputValue.length > 0 ? 'text-primary-inverse' : 'text-secondary'
                            )}
                        />
                    </ButtonPrimitive>
                </label>

                {items.length > 0 && (
                    <Autocomplete.List className="p-2 grow border-t border-primary flex flex-col gap-px">
                        {items.map((item, index) => {
                            const isAskAi = item.type === 'ask-ai'
                            const isSuggestion = item.type === 'suggestion'
                            const isRecent = item.type === 'recent'
                            const isFirstSuggestion =
                                isSuggestion && items.findIndex((i) => i.type === 'suggestion') === index
                            const isFirstRecent = isRecent && items.findIndex((i) => i.type === 'recent') === index

                            return (
                                <div key={item.id}>
                                    {isFirstSuggestion && (
                                        <div className="px-2 py-1.5 text-xxs font-medium text-tertiary uppercase tracking-wide">
                                            Suggested AI Prompts
                                        </div>
                                    )}
                                    {isFirstRecent && (
                                        <div className="px-2 py-1.5 text-xxs font-medium text-tertiary uppercase tracking-wide mt-2">
                                            Recent items
                                        </div>
                                    )}
                                    <Autocomplete.Item
                                        value={item}
                                        onClick={() => handleItemSelect(item)}
                                        className={cn(
                                            'flex items-center gap-3 px-2 py-2 rounded-md cursor-pointer',
                                            'hover:bg-fill-button-tertiary-hover',
                                            'data-[highlighted]:bg-fill-button-tertiary-active',
                                            'transition-colors duration-100',
                                            isAskAi && 'bg-fill-secondary'
                                        )}
                                    >
                                        {item.icon && (
                                            <span
                                                className={cn(
                                                    'shrink-0',
                                                    isAskAi ? 'text-[#b62ad9]' : 'text-secondary'
                                                )}
                                            >
                                                {item.icon}
                                            </span>
                                        )}
                                        <div className="flex flex-col min-w-0 flex-1">
                                            <span className={cn('text-sm truncate', isAskAi && 'font-medium')}>
                                                {item.label}
                                            </span>
                                            {item.description && !isAskAi && (
                                                <span className="text-xxs text-tertiary">{item.description}</span>
                                            )}
                                        </div>
                                        {isAskAi && <span className="text-xxs text-tertiary shrink-0">↵ Enter</span>}
                                    </Autocomplete.Item>
                                </div>
                            )
                        })}
                    </Autocomplete.List>
                )}
            </div>
        </Autocomplete.Root>
    )
}
