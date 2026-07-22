import { PluginKey } from '@tiptap/pm/state'
import { Editor, Extension, ReactRenderer } from '@tiptap/react'
import Suggestion from '@tiptap/suggestion'
import { forwardRef } from 'react'

import { EditorRange } from 'lib/components/RichContentEditor/types'
import { Popover } from 'lib/lemon-ui/Popover'

import type { MacroActionsApi, MacroApi } from '../../generated/api.schemas'
import { MacroVariableValues } from '../Editor/macroVariables'
import { applyMacroToEditor } from './applyMacro'
import { MacroPicker, MacroPickerRef } from './MacroPicker'

export interface MacrosExtensionOptions {
    enabled: boolean
    /** Resolves the current ticket's variable values at insert time. */
    getVariables: () => MacroVariableValues
    /** Applies a macro's ticket actions when one is inserted. */
    onApplyActions?: (actions: MacroActionsApi) => void
}

type MacroSuggestionProps = {
    editor: Editor
    range: EditorRange
    query?: string
    decorationNode?: any
    options: MacrosExtensionOptions
    onClose?: () => void
}

const MacroSuggestionPopover = forwardRef<MacroPickerRef, MacroSuggestionProps>(function MacroSuggestionPopover(
    { editor, range, query, decorationNode, options, onClose },
    ref
): JSX.Element {
    const onSelect = (macro: MacroApi): void => {
        applyMacroToEditor(editor, macro, {
            variables: options.getVariables(),
            range,
            onApplyActions: options.onApplyActions,
        })
        onClose?.()
    }

    return (
        <Popover
            placement="bottom-start"
            fallbackPlacements={['top-start', 'right-start']}
            overlay={<MacroPicker ref={ref} query={query} onSelect={onSelect} />}
            referenceElement={decorationNode}
            visible
            onClickOutside={onClose}
        />
    )
})

const MacrosPluginKey = new PluginKey('macros')

export const MacrosExtension = Extension.create<MacrosExtensionOptions>({
    name: 'macros',

    addOptions() {
        return {
            enabled: false,
            getVariables: () => ({}),
            onApplyActions: undefined,
        }
    },

    addProseMirrorPlugins() {
        if (!this.options.enabled) {
            return []
        }
        const extensionOptions = this.options
        return [
            Suggestion({
                pluginKey: MacrosPluginKey,
                editor: this.editor,
                char: '/',
                // Only trigger when `/` starts a line so it doesn't fire on ordinary reply text
                // (URLs, "and/or", "24/7"). The toolbar macro button handles mid-text insertion.
                startOfLine: true,
                render: () => {
                    let renderer: ReactRenderer<MacroPickerRef>

                    return {
                        onStart: (props) => {
                            renderer = new ReactRenderer(MacroSuggestionPopover, {
                                props: { ...props, options: extensionOptions },
                                editor: props.editor,
                            })
                        },
                        onUpdate(props) {
                            renderer.updateProps({ ...props, options: extensionOptions })
                        },
                        onKeyDown(props) {
                            if (props.event.key === 'Escape') {
                                renderer.destroy()
                                return true
                            }
                            return renderer.ref?.onKeyDown(props.event) ?? false
                        },
                        onExit() {
                            renderer.destroy()
                        },
                    }
                },
            }),
        ]
    },
})
