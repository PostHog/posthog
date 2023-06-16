import { Extension } from '@tiptap/core'
import Suggestion, { SuggestionOptions } from '@tiptap/suggestion'

import { FloatingMenu, ReactRenderer } from '@tiptap/react'
import { LemonButton, LemonButtonWithDropdown } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { notebookLogic } from './notebookLogic'
import { IconCohort, IconPlus, IconQueryEditor, IconRecording, IconTableChart } from 'lib/lemon-ui/icons'
import { useCallback } from 'react'
import { isCurrentNodeEmpty } from './utils'
import { NotebookNodeType } from '~/types'
import { examples } from '~/queries/examples'
import { useKeyboardNavigation } from 'lib/lemon-ui/LemonMenu/useKeyboardNavigation'
import { LemonMenuOverlay, isLemonMenuSection } from 'lib/lemon-ui/LemonMenu/LemonMenu'

export function SlashCommands(): JSX.Element | null {
    const { editor } = useValues(notebookLogic)
    const { insertPostHogNode } = useActions(notebookLogic)

    const items = [
        {
            title: (
                <div className="flex items-center gap-1 border-b pb-1">
                    <LemonButton
                        status="primary-alt"
                        size="small"
                        onClick={() => editor?.chain().focus().toggleHeading({ level: 1 }).run()}
                    >
                        H1
                    </LemonButton>
                    <LemonButton
                        status="primary-alt"
                        size="small"
                        onClick={() => editor?.chain().focus().toggleHeading({ level: 2 }).run()}
                    >
                        H2
                    </LemonButton>
                    <LemonButton
                        status="primary-alt"
                        size="small"
                        onClick={() => editor?.chain().focus().toggleHeading({ level: 3 }).run()}
                    >
                        H3
                    </LemonButton>
                </div>
            ),
            items: [
                {
                    icon: <IconRecording />,
                    label: 'Session Replays',
                    onClick: () => {
                        insertPostHogNode(NotebookNodeType.RecordingPlaylist)
                    },
                },
                {
                    icon: <IconTableChart />,
                    label: 'Events',
                    onClick: () => {
                        insertPostHogNode(NotebookNodeType.Query, {
                            query: examples['EventsTableFull'],
                        })
                    },
                },
                {
                    icon: <IconQueryEditor />,
                    label: 'HoqQL',
                    onClick: () => {
                        insertPostHogNode(NotebookNodeType.Query, {
                            query: examples['HogQLTable'],
                        })
                    },
                },
                {
                    icon: <IconCohort />,
                    label: 'Persons',
                    onClick: () => {
                        insertPostHogNode(NotebookNodeType.Query, {
                            query: examples['PersonsTableFull'],
                        })
                    },
                },
            ],
        },
    ]

    const { referenceRef, itemsRef } = useKeyboardNavigation<HTMLDivElement, HTMLButtonElement>(
        items.flatMap((item) => (item && isLemonMenuSection(item) ? item.items : item)).length
    )

    console.log('JERE?!')

    return (
        <div ref={referenceRef}>
            <LemonMenuOverlay items={items} tooltipPlacement={'right'} itemsRef={itemsRef} />
        </div>
    )
}

export function FloatingControls(): JSX.Element | null {
    const { editor } = useValues(notebookLogic)

    const shouldShow = useCallback((): boolean => {
        if (!editor) {
            return false
        }
        if (editor.view.hasFocus() && editor.isEditable && editor.isActive('paragraph') && isCurrentNodeEmpty(editor)) {
            return true
        }

        return false
    }, [editor])

    return editor ? (
        <FloatingMenu
            editor={editor}
            tippyOptions={{ duration: 100, placement: 'left' }}
            className="NotebookFloatingButton"
            shouldShow={shouldShow}
        >
            <LemonButtonWithDropdown
                size="small"
                icon={<IconPlus />}
                dropdown={{
                    overlay: <SlashCommands />,
                    placement: 'right-start',
                    fallbackPlacements: ['left-start'],
                    actionable: true,
                    closeParentPopoverOnClickInside: true,
                }}
            />
        </FloatingMenu>
    ) : null
}

export const SlashCommandsExtension = Extension.create({
    name: 'commands',

    addProseMirrorPlugins() {
        return [
            Suggestion({
                editor: this.editor,
                char: '/',
                startOfLine: true,
                command: ({ editor, range, props }) => {
                    console.log('COMMAND', props, props.command)
                    props.command({ editor, range })
                },
                items: ({ query }) => {
                    console.log('ITEMS')

                    return [
                        {
                            title: 'H1',
                            command: ({ editor, range }) => {
                                editor.chain().focus().deleteRange(range).setNode('heading', { level: 1 }).run()
                            },
                        },
                        {
                            title: 'H2',
                            command: ({ editor, range }) => {
                                editor.chain().focus().deleteRange(range).setNode('heading', { level: 2 }).run()
                            },
                        },
                        {
                            title: 'bold',
                            command: ({ editor, range }) => {
                                editor.chain().focus().deleteRange(range).setMark('bold').run()
                            },
                        },
                        {
                            title: 'italic',
                            command: ({ editor, range }) => {
                                editor.chain().focus().deleteRange(range).setMark('italic').run()
                            },
                        },
                    ]
                        .filter((item) => item.title.toLowerCase().startsWith(query.toLowerCase()))
                        .slice(0, 10)
                },

                render: () => {
                    console.log('RENDER')
                    let renderer: ReactRenderer

                    return {
                        onStart: (props) => {
                            console.log('START', props)
                            renderer = new ReactRenderer(SlashCommands, {
                                props,
                                editor: props.editor,
                            })

                            if (!props.clientRect) {
                                return
                            }

                            // let popup = tippy('body', {
                            //     getReferenceClientRect: props.clientRect,
                            //     appendTo: () => document.body,
                            //     content: component.element,
                            //     showOnCreate: true,
                            //     interactive: true,
                            //     trigger: 'manual',
                            //     placement: 'bottom-start',
                            // })
                        },

                        onUpdate(props) {
                            renderer.updateProps(props)

                            if (!props.clientRect) {
                                return
                            }

                            // popup[0].setProps({
                            //     getReferenceClientRect: props.clientRect,
                            // })
                        },

                        onKeyDown(props) {
                            // if (props.event.key === 'Escape') {
                            //     popup[0].hide()
                            //     return true
                            // }
                            // return component.ref?.onKeyDown(props)

                            return false
                        },

                        onExit() {
                            // popup[0].destroy()
                            renderer.destroy()
                        },
                    }
                },
            }),
        ]
    },
})
