import { Autocomplete } from '@base-ui/react/autocomplete'
import { Popover } from '@base-ui/react/popover'
import { useActions, useValues } from 'kea'
import { useEffect, useMemo, useRef, useState } from 'react'

import {
    IconActivity,
    IconArrowRight,
    IconAtSign,
    IconFlask,
    IconGraph,
    IconMemory,
    IconMessage,
    IconPieChart,
    IconRewindPlay,
    IconRocket,
    IconSupport,
    IconThumbsUp,
    IconToggle,
} from '@posthog/icons'

import { TaxonomicFilter } from 'lib/components/TaxonomicFilter/TaxonomicFilter'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { TextareaPrimitive } from 'lib/ui/TextareaPrimitive/TextareaPrimitive'
import { cn } from 'lib/utils/css-classes'

import { ContextTags } from '../Context'
import { TaxonomicItem, maxContextLogic } from '../maxContextLogic'
import { maxLogic } from '../maxLogic'
import { maxThreadLogic } from '../maxThreadLogic'

interface SuggestionItem {
    id: string
    label: string // What's displayed in the dropdown
    value: string // What gets put in the input
    description: string
    icon?: JSX.Element
    isCommand?: boolean
}

const SLASH_COMMANDS: SuggestionItem[] = [
    {
        id: 'init',
        label: '/init',
        value: '/init',
        description: 'Set up knowledge about your product & business',
        icon: <IconRocket />,
        isCommand: true,
    },
    {
        id: 'remember',
        label: '/remember [information]',
        value: '/remember ',
        description: "Add [information] to PostHog AI's project-level memory",
        icon: <IconMemory />,
        isCommand: true,
    },
    {
        id: 'usage',
        label: '/usage',
        value: '/usage',
        description: 'View AI credit usage for this conversation',
        icon: <IconActivity />,
        isCommand: true,
    },
    {
        id: 'feedback',
        label: '/feedback [your feedback]',
        value: '/feedback ',
        description: 'Share feedback about your PostHog AI experience',
        icon: <IconThumbsUp />,
        isCommand: true,
    },
    {
        id: 'ticket',
        label: '/ticket',
        value: '/ticket',
        description: 'Create a support ticket with a summary of this conversation',
        icon: <IconSupport />,
        isCommand: true,
    },
]

const MOCK_SUGGESTIONS: SuggestionItem[] = [
    {
        id: 's1',
        label: 'Show me user retention over the last 30 days',
        value: 'Show me user retention over the last 30 days',
        description: 'Product analytics',
        icon: <IconGraph />,
    },
    {
        id: 's2',
        label: 'Which features have the highest adoption rate?',
        value: 'Which features have the highest adoption rate?',
        description: 'Feature flags',
        icon: <IconToggle />,
    },
    {
        id: 's3',
        label: 'Create a funnel for our signup flow',
        value: 'Create a funnel for our signup flow',
        description: 'Product analytics',
        icon: <IconGraph />,
    },
    {
        id: 's4',
        label: 'How many active users do we have this week?',
        value: 'How many active users do we have this week?',
        description: 'Web analytics',
        icon: <IconPieChart />,
    },
    {
        id: 's5',
        label: 'Show me the most common user paths',
        value: 'Show me the most common user paths',
        description: 'Product analytics',
        icon: <IconGraph />,
    },
    {
        id: 's6',
        label: 'What events are most correlated with conversion?',
        value: 'What events are most correlated with conversion?',
        description: 'Experiments',
        icon: <IconFlask />,
    },
    {
        id: 's7',
        label: 'Create a survey to collect NPS scores',
        value: 'Create a survey to collect NPS scores',
        description: 'Surveys',
        icon: <IconMessage />,
    },
    {
        id: 's8',
        label: 'Show me session recordings from frustrated users',
        value: 'Show me session recordings from frustrated users',
        description: 'Session replay',
        icon: <IconRewindPlay />,
    },
]

type InputMode = 'commands' | 'suggestions'

interface AutocompleteListContentProps {
    mode: InputMode
    items: SuggestionItem[]
    onItemSelect: (item: SuggestionItem) => void
}

function AutocompleteListContent({ mode, items, onItemSelect }: AutocompleteListContentProps): JSX.Element {
    // Chunk items into rows of 2 for grid layout
    const rows = useMemo(() => {
        const result: SuggestionItem[][] = []
        for (let i = 0; i < items.length; i += 2) {
            result.push(items.slice(i, i + 2))
        }
        return result
    }, [items])

    if (mode === 'commands') {
        return (
            <>
                {items.map((item) => (
                    <Autocomplete.Item
                        key={item.id}
                        value={item}
                        onClick={() => onItemSelect(item)}
                        className={cn(
                            'AiFirstInput__item flex items-start gap-3 px-3 py-2.5 rounded-md cursor-pointer',
                            'hover:bg-fill-button-tertiary-hover',
                            'data-[highlighted]:bg-fill-button-tertiary-active',
                            'transition-colors duration-100'
                        )}
                    >
                        {item.icon && (
                            <span className="AiFirstInput__icon mt-0.5 text-secondary shrink-0">{item.icon}</span>
                        )}
                        <div className="flex flex-col min-w-0">
                            <span className="AiFirstInput__value text-sm font-mono font-medium">{item.label}</span>
                            <span className="AiFirstInput__description text-xxs text-secondary">
                                {item.description}
                            </span>
                        </div>
                    </Autocomplete.Item>
                ))}
            </>
        )
    }

    // Default: suggestions grid
    return (
        <>
            {rows.map((row, rowIndex) => (
                <Autocomplete.Row key={rowIndex} className="flex gap-2 mb-2 last:mb-0">
                    {row.map((item) => (
                        <Autocomplete.Item
                            key={item.id}
                            value={item}
                            onClick={() => onItemSelect(item)}
                            className={cn(
                                'AiFirstInput__item flex-1 flex flex-col gap-2 p-3 rounded-lg cursor-pointer',
                                'border border-primary',
                                'hover:bg-fill-button-tertiary-hover hover:border-secondary',
                                'data-[highlighted]:bg-fill-button-tertiary-active data-[highlighted]:border-secondary',
                                'transition-colors duration-100'
                            )}
                        >
                            <div className="flex items-center gap-2">
                                {item.icon && (
                                    <span className="AiFirstInput__icon text-secondary shrink-0">{item.icon}</span>
                                )}
                                <span className="AiFirstInput__description text-xs text-secondary font-medium">
                                    {item.description}
                                </span>
                            </div>
                            <span className="AiFirstInput__value text-sm leading-snug">{item.label}</span>
                        </Autocomplete.Item>
                    ))}
                </Autocomplete.Row>
            ))}
        </>
    )
}

function getInputMode(inputValue: string): InputMode {
    if (inputValue.startsWith('/')) {
        return 'commands'
    }
    return 'suggestions'
}

export function AiFirstInput(): JSX.Element {
    const { question } = useValues(maxLogic)
    const { setQuestion } = useActions(maxLogic)
    const { askMax } = useActions(maxThreadLogic)
    const { threadLoading, submissionDisabledReason } = useValues(maxThreadLogic)
    const inputRef = useRef<HTMLInputElement>(null)
    const [inputValue, setInputValue] = useState(question)
    const { handleTaxonomicFilterChange } = useActions(maxContextLogic)
    const [isTaxonomicFilterOpen, setIsTaxonomicFilterOpen] = useState(false)
    const { contextTagItems } = useValues(maxContextLogic)
    const [isOpen, setIsOpen] = useState(false)

    const inputMode = getInputMode(inputValue)
    const isSlashCommand = inputMode === 'commands'

    const showPlaceholder = inputValue.length === 0 && contextTagItems.length === 0

    // Check if input exactly matches a suggestion value (user selected an item)
    const isExactMatch = useMemo(() => {
        const allItems = [...SLASH_COMMANDS, ...MOCK_SUGGESTIONS]
        return allItems.some((item) => item.value === inputValue)
    }, [inputValue])

    // Build flat items list for Autocomplete.Root
    const items = useMemo(() => {
        // Hide suggestions when input matches a selected item (ready to submit)
        // or when context tags are present
        if (isExactMatch || contextTagItems.length > 0) {
            return []
        }

        if (isSlashCommand) {
            const query = inputValue.toLowerCase()
            return SLASH_COMMANDS.filter((cmd) => cmd.label.toLowerCase().startsWith(query))
        }

        if (!inputValue) {
            return MOCK_SUGGESTIONS
        }
        const query = inputValue.toLowerCase()
        return MOCK_SUGGESTIONS.filter((s) => s.label.toLowerCase().includes(query))
    }, [inputValue, isSlashCommand, isExactMatch, contextTagItems.length])

    useEffect(() => {
        setInputValue(question)
    }, [question])

    const handleValueChange = (value: string): void => {
        // When user types "/", don't let autocomplete override with a non-slash suggestion
        // But allow deletion (shorter value) or slash commands
        const isDeleting = value.length < inputValue.length
        if (inputValue.startsWith('/') && !value.startsWith('/') && !isDeleting) {
            return
        }

        setInputValue(value)
        setQuestion(value)
    }

    const handleItemSelect = (item: SuggestionItem): void => {
        // Don't select non-command items when user is typing a slash command
        if (inputValue.startsWith('/') && !item.isCommand) {
            return
        }
        setInputValue(item.value)
        setQuestion(item.value)
        inputRef.current?.focus()
    }

    const handleSubmit = (): void => {
        if (inputValue && !submissionDisabledReason && !threadLoading) {
            askMax(inputValue)
        }
    }

    return (
        <Popover.Root open={isTaxonomicFilterOpen} onOpenChange={setIsTaxonomicFilterOpen}>
            <Autocomplete.Root
                open={isOpen}
                onOpenChange={setIsOpen}
                value={inputValue}
                onValueChange={handleValueChange}
                items={items}
                itemToStringValue={(item: SuggestionItem) => item.value}
                openOnInputClick={inputValue.length === 0}
                mode="none"
                autoHighlight="always"
                grid={inputMode === 'suggestions'}
            >
                <div className="AiFirstInput relative w-full">
                    <label
                        htmlFor="ai-first-input"
                        className="flex flex-col h-auto w-full border text-sm outline-none relative border-primary bg-surface-primary text-input-primitive--height-lg input-like gap-1 focus-within:border-secondary rounded-lg pt-3 px-2 [--input-ring-size:2px] [--input-ring-color:#b62ad9]"
                    >
                        <span className="relative flex flex-col gap-1">
                            {showPlaceholder && (
                                <span className="text-tertiary absolute left-0 text-sm z-1 pointer-events-none">
                                    {isSlashCommand ? 'Type a command' : 'Ask a question'}
                                    <span className="text-tertiary/50 contrast-more:opacity-100 transition-opacity duration-300">
                                        &nbsp;/ for commands
                                    </span>
                                </span>
                            )}
                            <ContextTags size="small" inline />
                            <Autocomplete.Input
                                id="ai-first-input"
                                ref={inputRef}
                                onKeyDown={(e) => {
                                    if (e.key === 'Enter' && !e.shiftKey) {
                                        // Only submit if no suggestions are shown (popup closed)
                                        if (items.length === 0) {
                                            e.preventDefault()
                                            handleSubmit()
                                        }
                                        // Otherwise let Autocomplete handle Enter for item selection
                                    }
                                }}
                                render={(props) => (
                                    <TextareaPrimitive
                                        className="border-none resize-none min-h-14 p-0"
                                        wrapperClassName={cn(
                                            'flex-1',
                                            'text-primary placeholder:text-tertiary',
                                            'transition-all duration-200'
                                        )}
                                        {...props}
                                        style={{ height: (props.style?.height as number) ?? 0 }}
                                    />
                                )}
                            />
                        </span>
                        {/* <div className="sticky bottom-0 bg-surface-primary border-t border-primary px-3 py-1.5 text-xxs text-muted-alt font-medium select-none flex items-center gap-1">
                                    {inputMode === 'suggestions' ? (
                                        <>
                                            <KeyboardShortcut arrowup arrowright arrowdown arrowleft preserveOrder /> to
                                            navigate
                                        </>
                                    ) : (
                                        <>
                                            <KeyboardShortcut arrowup arrowdown /> to navigate
                                        </>
                                    )}
                                    <span className="mx-1">•</span>
                                    <KeyboardShortcut enter /> to select
                                    <span className="mx-1">•</span>
                                    <KeyboardShortcut escape /> to close
                                    {inputMode === 'suggestions' && (
                                        <>
                                            <span className="mx-1">•</span>
                                            <KeyboardShortcut forwardslash /> for commands
                                        </>
                                    )}
                                    {inputMode === 'commands' && inputValue === '/' && (
                                        <>
                                            <span className="mx-1">•</span>
                                            <KeyboardShortcut delete /> for suggestions
                                        </>
                                    )}
                                </div> */}
                        <div className="flex items-center justify-end gap-1 pb-2">
                            <Popover.Trigger
                                render={
                                    <ButtonPrimitive tooltip="Add context" iconOnly>
                                        <IconAtSign className="size-4 text-secondary stroke-2" />
                                    </ButtonPrimitive>
                                }
                            />

                            <ButtonPrimitive
                                iconOnly
                                className={cn(
                                    'rounded-full',
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
                        </div>
                    </label>

                    <Autocomplete.Empty>
                        <div className="px-4 py-3 text-secondary text-sm">No suggestions found.</div>
                    </Autocomplete.Empty>
                    <Autocomplete.List className="AiFirstInput__list p-2 grow overflow-y-auto empty:hidden">
                        <AutocompleteListContent mode={inputMode} items={items} onItemSelect={handleItemSelect} />
                    </Autocomplete.List>
                </div>
            </Autocomplete.Root>

            <Popover.Portal>
                <Popover.Positioner sideOffset={22} side="top" anchor={inputRef} align="start">
                    <Popover.Popup className="relative z-[var(--z-popover)] origin-[var(--transform-origin)]  w-[var(--anchor-width)] p-2 rounded-lg bg-surface-primary border border-primary overflow-hidden data-[ending-style]:scale-90 data-[ending-style]:opacity-0 data-[starting-style]:scale-90 data-[starting-style]:opacity-0 show-scrollbar-on-hover max-h-[calc(var(--available-height)-var(--scene-layout-header-height)-(var(--spacing)*4)))]">
                        <TaxonomicFilterPopover
                            handleTaxonomicFilterChange={(value, type, item) => {
                                handleTaxonomicFilterChange(
                                    value as string,
                                    type as TaxonomicFilterGroupType,
                                    item as TaxonomicItem
                                )
                                setIsTaxonomicFilterOpen(false)
                                inputRef.current?.focus()
                            }}
                        />
                    </Popover.Popup>
                </Popover.Positioner>
            </Popover.Portal>
        </Popover.Root>
    )
}

function TaxonomicFilterPopover({
    handleTaxonomicFilterChange,
}: {
    handleTaxonomicFilterChange: (value: string, type: string, item: any) => void
}): JSX.Element {
    const { taxonomicGroupTypes, mainTaxonomicGroupType } = useValues(maxContextLogic)

    return (
        <TaxonomicFilter
            groupType={mainTaxonomicGroupType}
            taxonomicGroupTypes={taxonomicGroupTypes}
            value={undefined}
            onChange={({ type }, payload, item) => {
                handleTaxonomicFilterChange(payload as string, type, item)
            }}
            width="100%"
        />
    )
}
