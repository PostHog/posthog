import { PluginKey } from '@tiptap/pm/state'
import { Editor, Extension, ReactRenderer } from '@tiptap/react'
import Suggestion, { exitSuggestion } from '@tiptap/suggestion'
import { useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import type { EditorRange } from 'lib/components/RichContentEditor/types'
import { Popover } from 'lib/lemon-ui/Popover'

import type { TicketMacroApi } from 'products/conversations/frontend/generated/api.schemas'

import { isStartOfMacroSlash, macroPreview } from './renderMacro'
import { supportMacrosLogic } from './supportMacrosLogic'

type MacroSuggestionProps = {
    range: EditorRange
    query: string
    editor: Editor
    onInsert: (macro: TicketMacroApi) => void
    onClose: () => void
}

function matchingMacros(macros: TicketMacroApi[], query: string): TicketMacroApi[] {
    const needle = query.trim().toLowerCase()
    const matches = needle
        ? macros.filter(
              (macro) => macro.name.toLowerCase().includes(needle) || (macro.shortcut ?? '').startsWith(needle)
          )
        : macros
    return matches.slice(0, 8)
}

function MacroSuggestionPanel({ range, query, editor, onInsert, onClose }: MacroSuggestionProps): JSX.Element {
    const { macrosSorted } = useValues(supportMacrosLogic)
    const matches = matchingMacros(macrosSorted, query)

    const choose = (macro: TicketMacroApi): void => {
        editor.chain().focus().deleteRange(range).run()
        onInsert(macro)
        onClose()
    }

    return (
        <div className="flex w-72 max-w-full flex-col gap-0.5 p-1">
            {matches.length === 0 ? (
                <span className="px-2 py-1 text-sm text-muted">No macros match.</span>
            ) : (
                matches.map((macro) => (
                    <LemonButton key={macro.id} fullWidth size="small" onClick={() => choose(macro)}>
                        <span className="flex min-w-0 flex-col items-start">
                            <span className="truncate">
                                {macro.name}
                                {macro.shortcut ? <span className="text-muted"> /{macro.shortcut}</span> : null}
                            </span>
                            <span className="max-w-full truncate text-xs text-muted">{macroPreview(macro.body)}</span>
                        </span>
                    </LemonButton>
                ))
            )}
        </div>
    )
}

function MacroSuggestionPopover({
    decorationNode,
    ...props
}: MacroSuggestionProps & { decorationNode?: HTMLElement | null }): JSX.Element {
    return (
        <Popover
            placement="bottom-start"
            fallbackPlacements={['top-start']}
            padded={false}
            overlay={<MacroSuggestionPanel {...props} />}
            referenceElement={decorationNode ?? null}
            visible
            onClickOutside={props.onClose}
        >
            <span />
        </Popover>
    )
}

export const MacroSuggestionPluginKey = new PluginKey('macroSuggestion')

export const MacroSuggestionExtension = Extension.create<{
    getOnInsert: () => ((macro: TicketMacroApi) => void) | undefined
}>({
    name: 'macroSuggestion',

    addOptions() {
        return { getOnInsert: () => undefined }
    },

    addProseMirrorPlugins() {
        const getOnInsert = this.options.getOnInsert

        return [
            Suggestion({
                pluginKey: MacroSuggestionPluginKey,
                editor: this.editor,
                char: '/',
                startOfLine: false,
                allowSpaces: false,
                allow: ({ state, range }) => {
                    const before = state.doc.textBetween(Math.max(0, range.from - 1), range.from)
                    return isStartOfMacroSlash(before)
                },
                render: () => {
                    let current: { editor: Editor; range: EditorRange; query: string } | null = null
                    let renderer: ReactRenderer<
                        unknown,
                        MacroSuggestionProps & { decorationNode?: HTMLElement | null }
                    > | null = null

                    const dismiss = (view: Editor['view']): void => {
                        exitSuggestion(view, MacroSuggestionPluginKey)
                        renderer?.destroy()
                        renderer = null
                        view.focus()
                    }

                    const suggestionProps = (props: {
                        editor: Editor
                        range: EditorRange
                        query: string
                        decorationNode?: Element | null
                    }): MacroSuggestionProps & { decorationNode?: HTMLElement | null } => {
                        current = { editor: props.editor, range: props.range, query: props.query }
                        return {
                            editor: props.editor,
                            range: props.range,
                            query: props.query,
                            decorationNode: (props.decorationNode as HTMLElement) ?? null,
                            onInsert: (macro: TicketMacroApi) => getOnInsert()?.(macro),
                            onClose: () => dismiss(props.editor.view),
                        }
                    }

                    return {
                        onStart: (props) => {
                            renderer = new ReactRenderer(MacroSuggestionPopover, {
                                editor: props.editor,
                                props: suggestionProps(props),
                            })
                        },
                        onUpdate(props) {
                            renderer?.updateProps(suggestionProps(props))
                        },
                        onKeyDown(props) {
                            if (props.event.key === 'Escape') {
                                dismiss(props.view)
                                return true
                            }
                            if (props.event.key === 'Enter' && current?.query) {
                                const { macrosSorted } = supportMacrosLogic.values
                                const match = matchingMacros(macrosSorted, current.query)[0]
                                const onInsert = getOnInsert()
                                if (match && onInsert) {
                                    current.editor.chain().focus().deleteRange(current.range).run()
                                    onInsert(match)
                                    dismiss(props.view)
                                    return true
                                }
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
        ]
    },
})
