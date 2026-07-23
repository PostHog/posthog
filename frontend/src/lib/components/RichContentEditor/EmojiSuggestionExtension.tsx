import { PluginKey } from '@tiptap/pm/state'
import type { EditorView } from '@tiptap/pm/view'
import { Editor, Extension, ReactRenderer } from '@tiptap/react'
import Suggestion, { exitSuggestion } from '@tiptap/suggestion'
import { useActions } from 'kea'

import { EmojiPickerPanel } from 'lib/components/EmojiPicker/EmojiPickerPanel'
import { emojiUsageLogic } from 'lib/lemon-ui/LemonTextArea/emojiUsageLogic'
import { Popover } from 'lib/lemon-ui/Popover'

import { EditorRange } from './types'

type EmojiSuggestionProps = {
    range: EditorRange
    /** What the user typed after the colon, in the editor, before focus moved into the picker */
    query: string
    editor: Editor
    /** Only mount + autofocus the picker once a character follows the colon */
    visible: boolean
    onClose: () => void
}

type EmojiSuggestionPopoverProps = EmojiSuggestionProps & {
    decorationNode?: HTMLElement | null
}

export function EmojiSuggestionPanel({
    range,
    query,
    editor,
    visible,
    onClose,
}: EmojiSuggestionProps): JSX.Element | null {
    const { emojiUsed } = useActions(emojiUsageLogic)

    if (!visible) {
        return null
    }

    const handleSelect = (emoji: string): void => {
        // Delete the `:query` still sitting in the editor (the range stops growing once
        // focus moves into the picker) and drop the emoji in its place.
        editor.chain().focus().deleteRange(range).insertContent(emoji).run()
        emojiUsed(emoji)
        onClose()
    }

    return (
        <div
            onKeyDown={(e) => {
                // Focus lives inside the picker, so the editor's suggestion keydown handler
                // never sees Escape — close from here instead.
                if (e.key === 'Escape') {
                    e.preventDefault()
                    onClose()
                }
            }}
        >
            <EmojiPickerPanel initialSearch={query} autoFocusSearch onEmojiSelect={handleSelect} />
        </div>
    )
}

function EmojiSuggestionPopover({ decorationNode, ...props }: EmojiSuggestionPopoverProps): JSX.Element {
    return (
        <Popover
            placement="bottom-start"
            fallbackPlacements={['top-start']}
            padded={false}
            overlay={<EmojiSuggestionPanel {...props} />}
            referenceElement={decorationNode ?? null}
            visible={props.visible}
            onClickOutside={props.onClose}
        >
            <span />
        </Popover>
    )
}

export const EmojiSuggestionPluginKey = new PluginKey('emojiSuggestion')

/**
 * Slack-style `:` emoji type-ahead for TipTap editors. Typing `:` immediately followed by a
 * character opens the emoji picker at the cursor, seeded with the typed query; picking an emoji
 * replaces the `:query` text. A bare `:` does nothing until a character follows it.
 *
 * Generic and dependency-free beyond the shared emoji picker — drop it into any editor's
 * `extensions` array.
 */
export const EmojiSuggestionExtension = Extension.create({
    name: 'emojiSuggestion',

    addProseMirrorPlugins() {
        return [
            Suggestion({
                pluginKey: EmojiSuggestionPluginKey,
                editor: this.editor,
                char: ':',
                startOfLine: false,
                // A space ends the match, so `: ` never opens the picker.
                allowSpaces: false,
                // Only treat the colon as a trigger when it starts a word — avoids `https://`,
                // `12:30`, `foo:bar`, etc.
                allow: ({ state, range }) => {
                    const before = state.doc.textBetween(Math.max(0, range.from - 1), range.from)
                    return before === '' || /\s/.test(before)
                },
                render: () => {
                    let renderer: ReactRenderer<unknown, EmojiSuggestionPopoverProps> | null = null

                    const dismiss = (view: EditorView): void => {
                        exitSuggestion(view, EmojiSuggestionPluginKey)
                        renderer?.destroy()
                        renderer = null
                    }

                    const buildProps = (props: {
                        editor: Editor
                        range: EditorRange
                        query: string
                        decorationNode?: Element | null
                    }): EmojiSuggestionPopoverProps => ({
                        editor: props.editor,
                        range: props.range,
                        query: props.query,
                        decorationNode: (props.decorationNode as HTMLElement) ?? null,
                        visible: props.query.length >= 1,
                        onClose: () => dismiss(props.editor.view),
                    })

                    return {
                        onStart: (props) => {
                            renderer = new ReactRenderer(EmojiSuggestionPopover, {
                                props: buildProps(props),
                                editor: props.editor,
                            })
                        },

                        onUpdate(props) {
                            renderer?.updateProps(buildProps(props))
                        },

                        onKeyDown() {
                            // While the popover is hidden focus is still in the editor; let those
                            // keystrokes through. Once it's open focus is in the picker, so this
                            // handler no longer fires and the picker owns navigation/Escape.
                            return false
                        },

                        onExit() {
                            renderer?.destroy()
                            renderer = null
                        },
                    }
                },
            }),
        ]
    },
})
