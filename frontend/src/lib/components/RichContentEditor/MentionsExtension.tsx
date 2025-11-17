import { PluginKey } from '@tiptap/pm/state'
import { Editor, Extension, ReactRenderer } from '@tiptap/react'
import Suggestion from '@tiptap/suggestion'
import Fuse from 'fuse.js'
import { useValues } from 'kea'
import { forwardRef, useCallback, useEffect, useImperativeHandle, useMemo, useState } from 'react'

import { LemonButton, ProfilePicture } from '@posthog/lemon-ui'

import { Popover } from 'lib/lemon-ui/Popover'
import { membersLogic } from 'scenes/organization/membersLogic'

import { OrganizationMemberType } from '~/types'

import { EditorRange, RichContentNodeType } from './types'

type MentionsProps = {
    range: EditorRange
    query?: string
    decorationNode?: any
    onClose?: () => void
    editor: Editor
}

type MentionsPopoverProps = MentionsProps & {
    visible: boolean
    children?: JSX.Element
}

type MentionsRef = {
    onKeyDown: (event: KeyboardEvent) => boolean
}

export const Mentions = forwardRef<MentionsRef, MentionsProps>(function SlashCommands(
    { range, onClose, query, editor }: MentionsProps,
    ref
): JSX.Element | null {
    const { meFirstMembers } = useValues(membersLogic)

    // We start with 1 because the first item is the text controls
    const [selectedIndex, setSelectedIndex] = useState(0)
    const [selectedHorizontalIndex, setSelectedHorizontalIndex] = useState(0)

    const fuse = useMemo(() => {
        return new Fuse(meFirstMembers, {
            keys: ['id', 'user.email', 'user.first_name', 'user.last_name'],
            threshold: 0.3,
        })
    }, [meFirstMembers])

    const filteredMembers = useMemo(() => {
        if (!query) {
            return meFirstMembers
        }
        return fuse.search(query).map((result) => result.item)
    }, [query, fuse, meFirstMembers])

    useEffect(() => {
        setSelectedIndex(0)
        setSelectedHorizontalIndex(0)
    }, [query])

    const execute = async (member: OrganizationMemberType): Promise<void> => {
        if (editor) {
            editor
                .chain()
                .focus()
                .deleteRange(range)
                .insertContentAt(range.from, [
                    {
                        type: RichContentNodeType.Mention,
                        attrs: {
                            id: member.user.id,
                        },
                    },
                ])
                .run()

            onClose?.()
        }
    }

    const onPressEnter = async (): Promise<void> => {
        const member = filteredMembers[selectedIndex]
        await execute(member)
    }
    const onPressUp = (): void => {
        setSelectedIndex(Math.max(selectedIndex - 1, -1))
    }
    const onPressDown = (): void => {
        setSelectedIndex(Math.min(selectedIndex + 1, filteredMembers.length - 1))
    }

    const onKeyDown = useCallback(
        (event: KeyboardEvent): boolean => {
            const keyMappings = {
                ArrowUp: onPressUp,
                ArrowDown: onPressDown,
                Enter: onPressEnter,
            }

            if (keyMappings[event.key]) {
                keyMappings[event.key]()
                return true
            }

            return false
        },
        // oxlint-disable-next-line exhaustive-deps
        [selectedIndex, selectedHorizontalIndex, filteredMembers]
    )

    // Expose the keydown handler to the tiptap extension
    useImperativeHandle(ref, () => ({ onKeyDown }), [onKeyDown])

    if (!editor) {
        return null
    }

    return (
        <div className="deprecated-space-y-px">
            {filteredMembers.map((member, index) => (
                <LemonButton
                    key={member.id}
                    fullWidth
                    icon={<ProfilePicture user={member.user} size="sm" />}
                    active={index === selectedIndex}
                    onClick={() => void execute(member)}
                >
                    <span className="ph-no-capture">{`${member.user.first_name} <${member.user.email}>`}</span>
                </LemonButton>
            ))}

            {filteredMembers.length === 0 && (
                <div className="text-secondary p-1">
                    No member matching <code>@{query}</code>
                </div>
            )}
        </div>
    )
})

const MentionsPopover = forwardRef<MentionsRef, MentionsPopoverProps>(function MentionsPopover(
    { visible = true, decorationNode, children, onClose, ...props }: MentionsPopoverProps,
    ref
): JSX.Element | null {
    return (
        <Popover
            placement="bottom-start"
            fallbackPlacements={['top-start', 'right-start']}
            overlay={<Mentions ref={ref} onClose={onClose} {...props} />}
            referenceElement={decorationNode}
            visible={visible}
            onClickOutside={onClose}
        >
            {children}
        </Popover>
    )
})

const MentionsPluginKey = new PluginKey('mentions')

export const MentionsExtension = Extension.create({
    name: 'mentions',

    addProseMirrorPlugins() {
        return [
            Suggestion({
                pluginKey: MentionsPluginKey,
                editor: this.editor,
                char: '@',
                startOfLine: false,
                render: () => {
                    let renderer: ReactRenderer<MentionsRef>

                    return {
                        onStart: (props) => {
                            renderer = new ReactRenderer(MentionsPopover, {
                                props: props,
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
