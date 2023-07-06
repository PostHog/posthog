import { Extension, Editor } from '@tiptap/core'
import { ReactRenderer } from '@tiptap/react'
import Suggestion from '@tiptap/suggestion'
import { Popover } from 'lib/lemon-ui/Popover'
import { forwardRef, useEffect, useImperativeHandle, useState } from 'react'

type BacklinkCommandsProps = {
    editor: Editor
    query?: string
    range?: Range
    decorationNode?: any
}

type BacklinkCommandsRef = {
    onKeyDown: (event: KeyboardEvent) => boolean
}

const BacklinkCommandsPopover = forwardRef<BacklinkCommandsRef, BacklinkCommandsProps>(function BacklinkCommandsPopover(
    props: BacklinkCommandsProps,
    ref
): JSX.Element | null {
    return (
        <Popover overlay={<BacklinkCommands ref={ref} {...props} />} visible referenceElement={props.decorationNode} />
    )
})

const BacklinkCommands = forwardRef<BacklinkCommandsRef, BacklinkCommandsProps>(function SlashCommands(
    { editor, query },
    ref
): JSX.Element | null {
    const [selectedIndex, setSelectedIndex] = useState(0)

    useEffect(() => {
        setSelectedIndex(0)
    }, [query])

    const onPressEnter = (): void => {
        const nodeAfter = editor.view.state.selection.$to.nodeAfter
        const overrideSpace = nodeAfter?.text?.startsWith(' ')

        if (overrideSpace) {
            // range.to += 1
        }

        // editor
        //     .chain()
        //     .focus()
        //     .insertContentAt(range, [
        //         {
        //             type: 'meme',
        //             attrs: {},
        //             // attrs: props,
        //         },
        //         {
        //             type: 'text',
        //             text: ' ',
        //         },
        //     ])
        //     .run()

        window.getSelection()?.collapseToEnd()
    }
    const onPressUp = (): void => {
        console.log(selectedIndex)
    }
    const onPressDown = (): void => {}
    const onPressLeft = (): void => {}
    const onPressRight = (): void => {}

    useImperativeHandle(ref, () => ({
        onKeyDown: (event: KeyboardEvent) => {
            const keyMappings = {
                ArrowUp: onPressUp,
                ArrowDown: onPressDown,
                ArrowLeft: onPressLeft,
                ArrowRight: onPressRight,
                Enter: onPressEnter,
            }

            if (keyMappings[event.key]) {
                keyMappings[event.key]()
                return true
            }

            return false
        },
    }))

    if (!editor) {
        return null
    }

    return <div className="">This is the list</div>
})

export const BacklinkCommandsExtension = Extension.create({
    name: 'backlink-commands',

    addProseMirrorPlugins() {
        return [
            Suggestion({
                editor: this.editor,
                char: '£',
                render: () => {
                    let renderer: ReactRenderer<BacklinkCommandsRef>

                    return {
                        onStart: (props) => {
                            renderer = new ReactRenderer(BacklinkCommandsPopover, {
                                props,
                                editor: props.editor,
                            })
                        },

                        onUpdate(props) {
                            renderer.updateProps(props)

                            if (!props.clientRect) {
                                return
                            }
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
