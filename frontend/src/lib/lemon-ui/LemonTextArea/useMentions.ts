import { useCallback, useState, useMemo } from 'react'
import { useValues } from 'kea'
import { membersLogic } from 'scenes/organization/membersLogic'
import Fuse from 'fuse.js'

export interface MentionsState {
    mentionsOpen: boolean
    mentionsQuery: string
    mentionsPosition: { top: number; left: number }
    mentionsStartIndex: number
    selectedMentionIndex: number
}

export interface UseMentionsProps {
    textAreaRef: React.RefObject<HTMLTextAreaElement>
    value?: string
    onChange?: (value: string) => void
}

export function useMentions({ textAreaRef, value, onChange }: UseMentionsProps): {
    mentionsOpen: boolean
    mentionsQuery: string
    mentionsPosition: { top: number; left: number }
    mentionsStartIndex: number
    selectedMentionIndex: number
    filteredMembers: any[]
    selectMention: (member: any) => void
    setMentionsOpen: (open: boolean) => void
    handleTextChange: (newValue: string) => void
    handleKeyDown: (e: React.KeyboardEvent<HTMLTextAreaElement>) => boolean
} {
    const { meFirstMembers } = useValues(membersLogic)

    // Mentions state
    const [mentionsOpen, setMentionsOpen] = useState(false)
    const [mentionsQuery, setMentionsQuery] = useState('')
    const [mentionsPosition, setMentionsPosition] = useState({ top: 0, left: 0 })
    const [mentionsStartIndex, setMentionsStartIndex] = useState(0)
    const [selectedMentionIndex, setSelectedMentionIndex] = useState(0)

    // Helper function to detect @ mentions
    const detectMentions = useCallback((text: string, cursorPosition: number) => {
        const beforeCursor = text.slice(0, cursorPosition)
        const lastAtIndex = beforeCursor.lastIndexOf('@')

        if (lastAtIndex === -1) {
            return null
        }

        // Check if there's a word boundary before the @
        const charBeforeAt = beforeCursor[lastAtIndex - 1]
        if (charBeforeAt && /\w/.test(charBeforeAt)) {
            return null
        }

        // Extract the query after @
        const queryAfterAt = beforeCursor.slice(lastAtIndex + 1)

        // Check if the query contains whitespace or newlines (invalid mention)
        if (/\s/.test(queryAfterAt)) {
            return null
        }

        return {
            startIndex: lastAtIndex,
            query: queryAfterAt,
        }
    }, [])

    // Helper function to get cursor position in pixels
    const getCursorPosition = useCallback((textarea: HTMLTextAreaElement, cursorIndex: number) => {
        const div = document.createElement('div')
        const style = getComputedStyle(textarea)

        // Copy textarea styles to div
        ;[
            'font-family',
            'font-size',
            'font-weight',
            'line-height',
            'letter-spacing',
            'padding-left',
            'padding-top',
            'padding-right',
            'padding-bottom',
            'border-left-width',
            'border-top-width',
            'border-right-width',
            'border-bottom-width',
            'white-space',
            'word-wrap',
            'word-break',
            'box-sizing',
        ].forEach((prop) => {
            div.style[prop as any] = style[prop as any]
        })

        div.style.position = 'absolute'
        div.style.visibility = 'hidden'
        div.style.whiteSpace = 'pre-wrap'
        div.style.width = style.width
        div.style.height = style.height
        div.style.overflow = 'hidden'
        div.style.zIndex = '-1000'

        const text = textarea.value
        const textBeforeCursor = text.slice(0, cursorIndex)
        const textAfterCursor = text.slice(cursorIndex)

        div.innerHTML = textBeforeCursor + '<span id="cursor-position"></span>' + textAfterCursor

        // Position the div at the same location as the textarea
        const textareaRect = textarea.getBoundingClientRect()
        div.style.top = textareaRect.top + window.scrollY + 'px'
        div.style.left = textareaRect.left + window.scrollX + 'px'

        document.body.appendChild(div)

        const cursorSpan = div.querySelector('#cursor-position')
        const cursorRect = cursorSpan?.getBoundingClientRect()

        const position = {
            top: (cursorRect?.top || 0) - textareaRect.top + textarea.scrollTop,
            left: (cursorRect?.left || 0) - textareaRect.left + textarea.scrollLeft,
        }

        document.body.removeChild(div)
        return position
    }, [])

    // Filter members for mentions
    const filteredMembers = useMemo(() => {
        const members = !mentionsQuery
            ? meFirstMembers.slice(0, 10) // Show first 10 members by default
            : new Fuse(meFirstMembers, {
                  keys: ['user.first_name', 'user.last_name', 'user.email'],
                  threshold: 0.3,
              })
                  .search(mentionsQuery)
                  .map((result) => result.item)
                  .slice(0, 10)

        // Reset selection when members change
        setSelectedMentionIndex(0)
        return members
    }, [meFirstMembers, mentionsQuery])

    // Handle mention selection
    const selectMention = useCallback(
        (member: any) => {
            const mentionText = `@${member.user.first_name}`
            const currentValue = value || ''
            const beforeMention = currentValue.slice(0, mentionsStartIndex)
            const afterMention = currentValue.slice(textAreaRef.current?.selectionStart || 0)
            const newValue = beforeMention + mentionText + afterMention

            onChange?.(newValue)
            setMentionsOpen(false)

            // Set cursor position after mention
            setTimeout(() => {
                const textarea = textAreaRef.current
                if (textarea) {
                    textarea.focus()
                    const cursorPos = beforeMention.length + mentionText.length
                    textarea.setSelectionRange(cursorPos, cursorPos)
                }
            }, 0)
        },
        [value, onChange, mentionsStartIndex, textAreaRef]
    )

    // Handle text change for mentions detection
    const handleTextChange = useCallback(
        (newValue: string) => {
            onChange?.(newValue)

            // Check for mentions after state update
            const textarea = textAreaRef.current
            if (textarea) {
                const cursorPosition = textarea.selectionStart
                const mention = detectMentions(newValue, cursorPosition)

                if (mention) {
                    setMentionsQuery(mention.query)
                    setMentionsStartIndex(mention.startIndex)

                    // Get cursor position for popover
                    const position = getCursorPosition(textarea, cursorPosition)
                    setMentionsPosition(position)
                    setMentionsOpen(true)
                } else {
                    setMentionsOpen(false)
                }
            }
        },
        [onChange, textAreaRef, detectMentions, getCursorPosition]
    )

    // Handle keyboard events for mentions
    const handleKeyDown = useCallback(
        (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
            if (mentionsOpen && filteredMembers.length > 0) {
                if (e.key === 'ArrowDown') {
                    e.preventDefault()
                    setSelectedMentionIndex((prev) => (prev < filteredMembers.length - 1 ? prev + 1 : 0))
                    return true // Indicate we handled the event
                } else if (e.key === 'ArrowUp') {
                    e.preventDefault()
                    setSelectedMentionIndex((prev) => (prev > 0 ? prev - 1 : filteredMembers.length - 1))
                    return true
                } else if (e.key === 'Enter' && !e.metaKey && !e.ctrlKey) {
                    e.preventDefault()
                    selectMention(filteredMembers[selectedMentionIndex])
                    return true
                } else if (e.key === 'Escape') {
                    e.preventDefault()
                    setMentionsOpen(false)
                    return true
                }
            }
            return false // We didn't handle the event
        },
        [mentionsOpen, filteredMembers, selectedMentionIndex, selectMention]
    )

    return {
        // State
        mentionsOpen,
        mentionsQuery,
        mentionsPosition,
        mentionsStartIndex,
        selectedMentionIndex,
        filteredMembers,

        // Actions
        selectMention,
        setMentionsOpen,
        handleTextChange,
        handleKeyDown,
    }
}
