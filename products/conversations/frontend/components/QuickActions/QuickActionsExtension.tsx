import { PluginKey } from '@tiptap/pm/state'
import { Editor, Extension, ReactRenderer } from '@tiptap/react'
import Suggestion from '@tiptap/suggestion'
import { forwardRef } from 'react'

import { EditorRange } from 'lib/components/RichContentEditor/types'
import { Popover } from 'lib/lemon-ui/Popover'

import type { QuickActionActionsApi, QuickActionApi } from '../../generated/api.schemas'
import { TemplateVariableValues } from '../Editor/templateVariables'
import { applyQuickAction } from './applyQuickAction'
import { QuickActionPicker, QuickActionPickerRef } from './QuickActionPicker'

export interface QuickActionsExtensionOptions {
    enabled: boolean
    /** Resolves the current ticket's variable values at insert time. */
    getVariables: () => TemplateVariableValues
    /** Applies a response quick action's ticket actions when one is inserted. */
    onApplyActions?: (actions: QuickActionActionsApi) => void
    /** Runs a workflow quick action against the ticket. */
    onRunWorkflow?: (quickAction: QuickActionApi) => void
}

type QuickActionSuggestionProps = {
    editor: Editor
    range: EditorRange
    query?: string
    decorationNode?: any
    options: QuickActionsExtensionOptions
    onClose?: () => void
}

const QuickActionSuggestionPopover = forwardRef<QuickActionPickerRef, QuickActionSuggestionProps>(
    function QuickActionSuggestionPopover(
        { editor, range, query, decorationNode, options, onClose },
        ref
    ): JSX.Element {
        const onSelect = (quickAction: QuickActionApi): void => {
            applyQuickAction(editor, quickAction, {
                variables: options.getVariables(),
                range,
                onApplyActions: options.onApplyActions,
                onRunWorkflow: options.onRunWorkflow,
            })
            onClose?.()
        }

        return (
            <Popover
                placement="bottom-start"
                fallbackPlacements={['top-start', 'right-start']}
                overlay={<QuickActionPicker ref={ref} query={query} onSelect={onSelect} />}
                referenceElement={decorationNode}
                visible
                onClickOutside={onClose}
            />
        )
    }
)

const QuickActionsPluginKey = new PluginKey('quickActions')

export const QuickActionsExtension = Extension.create<QuickActionsExtensionOptions>({
    name: 'quickActions',

    addOptions() {
        return {
            enabled: false,
            getVariables: () => ({}),
            onApplyActions: undefined,
            onRunWorkflow: undefined,
        }
    },

    addProseMirrorPlugins() {
        if (!this.options.enabled) {
            return []
        }
        const extensionOptions = this.options
        return [
            Suggestion({
                pluginKey: QuickActionsPluginKey,
                editor: this.editor,
                char: '/',
                // Only trigger when `/` starts a line so it doesn't fire on ordinary reply text
                // (URLs, "and/or", "24/7"). The toolbar quick-action button handles mid-text insertion.
                startOfLine: true,
                // Quick action names have spaces, so keep the query alive across them.
                allowSpaces: true,
                // Don't hijack a leading `/` inside a code block, where it's ordinary code.
                allow: ({ editor }) => !editor.isActive('codeBlock'),
                render: () => {
                    let renderer: ReactRenderer<QuickActionPickerRef>
                    const close = (): void => renderer?.destroy()

                    return {
                        onStart: (props) => {
                            renderer = new ReactRenderer(QuickActionSuggestionPopover, {
                                props: { ...props, options: extensionOptions, onClose: close },
                                editor: props.editor,
                            })
                        },
                        onUpdate(props) {
                            renderer.updateProps({ ...props, options: extensionOptions, onClose: close })
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
