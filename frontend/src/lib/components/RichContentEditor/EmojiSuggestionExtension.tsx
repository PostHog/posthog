import { Plugin, PluginKey } from '@tiptap/pm/state'
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
        // Position of a colon whose picker was Escaped. Suppresses the re-match that returning
        // focus to the editor would otherwise trigger; cleared once the caret leaves the token
        // (see the reset plugin below).
        let suppressedFrom: number | null = null

        return [
            Suggestion({
                pluginKey: EmojiSuggestionPluginKey,
                editor: this.editor,
                char: ':',
                startOfLine: false,
                // A space ends the match, so `: ` never opens the picker.
                allowSpaces: false,
                allow: ({ state, range, isActive }) => {
                    // Only trigger when the colon starts a word — avoids `https://`, `12:30`, `foo:bar`.
                    const before = state.doc.textBetween(Math.max(0, range.from - 1), range.from)
                    if (before !== '' && !/\s/.test(before)) {
                        return false
                    }
                    if (isActive) {
                        return true
                    }
                    if (suppressedFrom === range.from) {
                        return false
                    }
                    suppressedFrom = null
                    return true
                },
                render: () => {
                    let renderer: ReactRenderer<unknown, EmojiSuggestionPopoverProps> | null = null

                    const dismiss = (view: EditorView, from: number): void => {
                        suppressedFrom = from
                        exitSuggestion(view, EmojiSuggestionPluginKey)
                        renderer?.destroy()
                        renderer = null
                        // Hand focus back to the editor (it moved into the picker's search box) so
                        // the caret returns after the typed `:query` and typing continues.
                        view.focus()
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
                        onClose: () => dismiss(props.editor.view, props.range.from),
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

                        onKeyDown(props) {
                            // Escape only reaches here while focus is still in the editor (bare `:`,
                            // or before autofocus lands); once open, the panel owns Escape.
                            if (props.event.key === 'Escape') {
                                dismiss(props.view, props.range.from)
                                return true
                            }
                            return false
                        },

                        onExit() {
                            renderer?.destroy()
                            renderer = null
                        },
                    }
                },
            }),
            // Clear the dismissal memory once the caret leaves the Escaped token, so a fresh `:`
            // at (or returning to) that spot can reopen the picker.
            new Plugin({
                key: new PluginKey('emojiSuggestionSuppressionReset'),
                view: () => ({
                    update: (view) => {
                        if (suppressedFrom === null) {
                            return
                        }
                        const { doc, selection } = view.state
                        const stillOnToken =
                            selection.empty &&
                            selection.from > suppressedFrom &&
                            /^:\S*$/.test(doc.textBetween(suppressedFrom, selection.from))
                        if (!stillOnToken) {
                            suppressedFrom = null
                        }
                    },
                }),
            }),
        ]
    },
})
