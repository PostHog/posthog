import './AiFirstInput.scss'

import { Autocomplete } from '@base-ui/react/autocomplete'
import { useActions, useValues } from 'kea'
import { useEffect, useMemo, useRef, useState } from 'react'

import {
    IconActivity,
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

import { TextareaPrimitive } from 'lib/ui/TextareaPrimitive/TextareaPrimitive'
import { cn } from 'lib/utils/css-classes'

import { KeyboardShortcut } from '~/layout/navigation-3000/components/KeyboardShortcut'

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

export function AiFirstInput(): JSX.Element {
    const { question } = useValues(maxLogic)
    const { setQuestion } = useActions(maxLogic)
    const { askMax } = useActions(maxThreadLogic)
    const { threadLoading, submissionDisabledReason } = useValues(maxThreadLogic)

    const inputRef = useRef<HTMLInputElement>(null)
    const [inputValue, setInputValue] = useState(question)

    const isSlashCommand = inputValue.startsWith('/')

    // Check if input exactly matches a suggestion value (user selected an item)
    const isExactMatch = useMemo(() => {
        const allItems = [...SLASH_COMMANDS, ...MOCK_SUGGESTIONS]
        return allItems.some((item) => item.value === inputValue)
    }, [inputValue])

    const items = useMemo(() => {
        // Hide suggestions when input matches a selected item (ready to submit)
        if (isExactMatch) {
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
    }, [inputValue, isSlashCommand, isExactMatch])

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

    // For grid layout, chunk items into rows of 2
    const rows = useMemo(() => {
        const result: SuggestionItem[][] = []
        for (let i = 0; i < items.length; i += 2) {
            result.push(items.slice(i, i + 2))
        }
        return result
    }, [items])

    return (
        <Autocomplete.Root
            value={inputValue}
            onValueChange={handleValueChange}
            items={items}
            itemToStringValue={(item: SuggestionItem) => item.value}
            openOnInputClick
            mode="list"
            autoHighlight="always"
            grid={!isSlashCommand}
        >
            <div className="AiFirstInput relative w-full">
                <Autocomplete.Input
                    ref={inputRef}
                    placeholder={isSlashCommand ? 'Type a command...' : 'Ask a question...'}
                    className={cn(
                        'AiFirstInput__input w-full px-4 py-3 rounded-lg',
                        'border border-primary bg-surface-primary',
                        'text-primary placeholder:text-tertiary',
                        'focus:outline-none focus:ring-2 focus:ring-[#b62ad9]',
                        'transition-all duration-200'
                    )}
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
                    aria-label="Ask PostHog AI"
                    render={(props) => (
                        <TextareaPrimitive {...props} style={{ height: (props.style?.height as number) ?? 0 }} />
                    )}
                />

                <Autocomplete.Portal>
                    <Autocomplete.Positioner
                        className="AiFirstInput__positioner z-[100]"
                        sideOffset={10}
                        side="top"
                        align="start"
                    >
                        <Autocomplete.Popup className="flex flex-col AiFirstInput__popup rounded-lg border border-primary bg-surface-primary shadow-lg overflow-hidden max-h-96 w-[var(--anchor-width)] data-[ending-style]:scale-90 data-[ending-style]:opacity-0 data-[starting-style]:scale-90 data-[starting-style]:opacity-0 show-scrollbar-on-hover">
                            <Autocomplete.Empty>
                                <div className="px-4 py-3 text-secondary text-sm">No suggestions found.</div>
                            </Autocomplete.Empty>
                            <Autocomplete.List className="AiFirstInput__list p-2 grow overflow-y-auto">
                                {isSlashCommand
                                    ? // List layout for slash commands
                                      items.map((item) => (
                                          <Autocomplete.Item
                                              key={item.id}
                                              value={item}
                                              onClick={() => handleItemSelect(item)}
                                              className={cn(
                                                  'AiFirstInput__item flex items-start gap-3 px-3 py-2.5 rounded-md cursor-pointer',
                                                  'hover:bg-fill-tertiary',
                                                  'data-[highlighted]:bg-fill-tertiary',
                                                  'transition-colors duration-100'
                                              )}
                                          >
                                              {item.icon && (
                                                  <span className="AiFirstInput__icon mt-0.5 text-secondary shrink-0">
                                                      {item.icon}
                                                  </span>
                                              )}
                                              <div className="flex flex-col min-w-0">
                                                  <span className="AiFirstInput__value text-sm font-mono font-medium">
                                                      {item.label}
                                                  </span>
                                                  <span className="AiFirstInput__description text-xxs text-secondary">
                                                      {item.description}
                                                  </span>
                                              </div>
                                          </Autocomplete.Item>
                                      ))
                                    : // Grid layout for suggestions
                                      rows.map((row, rowIndex) => (
                                          <Autocomplete.Row key={rowIndex} className="flex gap-2 mb-2 last:mb-0">
                                              {row.map((item) => (
                                                  <Autocomplete.Item
                                                      key={item.id}
                                                      value={item}
                                                      onClick={() => handleItemSelect(item)}
                                                      className={cn(
                                                          'AiFirstInput__item flex-1 flex flex-col gap-2 p-3 rounded-lg cursor-pointer',
                                                          'border border-primary',
                                                          'hover:bg-fill-tertiary hover:border-secondary',
                                                          'data-[highlighted]:bg-fill-tertiary data-[highlighted]:border-secondary',
                                                          'transition-colors duration-100'
                                                      )}
                                                  >
                                                      <div className="flex items-center gap-2">
                                                          {item.icon && (
                                                              <span className="AiFirstInput__icon text-secondary shrink-0">
                                                                  {item.icon}
                                                              </span>
                                                          )}
                                                          <span className="AiFirstInput__description text-xs text-secondary font-medium">
                                                              {item.description}
                                                          </span>
                                                      </div>
                                                      <span className="AiFirstInput__value text-sm leading-snug">
                                                          {item.label}
                                                      </span>
                                                  </Autocomplete.Item>
                                              ))}
                                          </Autocomplete.Row>
                                      ))}
                            </Autocomplete.List>
                            <div className="sticky bottom-0 bg-surface-primary border-t border-primary px-3 py-1.5 text-xxs text-muted-alt font-medium select-none flex items-center gap-1">
                                {isSlashCommand ? (
                                    <>
                                        <KeyboardShortcut arrowup arrowdown /> to navigate
                                    </>
                                ) : (
                                    <>
                                        <KeyboardShortcut arrowup arrowright arrowdown arrowleft preserveOrder /> to
                                        navigate
                                    </>
                                )}
                                <span className="mx-1">•</span>
                                <KeyboardShortcut enter /> to select
                                <span className="mx-1">•</span>
                                <KeyboardShortcut escape /> to close
                                {!isSlashCommand ? (
                                    <>
                                        <span className="mx-1">•</span>
                                        <KeyboardShortcut forwardslash /> for commands
                                    </>
                                ) : inputValue === '/' ? (
                                    <>
                                        <span className="mx-1">•</span>
                                        <KeyboardShortcut delete /> for suggestions
                                    </>
                                ) : null}
                            </div>
                        </Autocomplete.Popup>
                    </Autocomplete.Positioner>
                </Autocomplete.Portal>
            </div>
        </Autocomplete.Root>
    )
}
