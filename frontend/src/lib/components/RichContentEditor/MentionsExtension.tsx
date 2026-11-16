import { PluginKey } from '@tiptap/pm/state'
import { Editor, Extension, ReactRenderer } from '@tiptap/react'
import Suggestion from '@tiptap/suggestion'
import { useActions, useValues } from 'kea'
import { forwardRef, useCallback, useEffect, useImperativeHandle, useMemo, useState } from 'react'

import { IconPeople } from '@posthog/icons'
import { LemonButton, ProfilePicture } from '@posthog/lemon-ui'

import { Popover } from 'lib/lemon-ui/Popover'
import { createFuse } from 'lib/utils/fuseSearch'
import { isKeyOf } from 'lib/utils/guards'

import { membersLogic } from '~/models/membersLogic'
import { OrganizationMemberType } from '~/types'

import type { RoleApi } from 'products/platform_features/frontend/generated/api.schemas'

import { mentionRolesLogic } from './mentionRolesLogic'
import { EditorRange, RichContentNodeType } from './types'

type MentionsProps = {
    range: EditorRange
    query?: string
    decorationNode?: any
    onClose?: () => void
    editor: Editor
    /** Roles to offer after the members. Omit to offer members only. */
    roles?: RoleApi[]
}

type MentionsPopoverProps = MentionsProps & {
    visible: boolean
    children?: JSX.Element
    includeRoles?: boolean
}

type MentionOption = { kind: 'member'; member: OrganizationMemberType } | { kind: 'role'; role: RoleApi }

type MentionsRef = {
    onKeyDown: (event: KeyboardEvent) => boolean
}

export const Mentions = forwardRef<MentionsRef, MentionsProps>(function SlashCommands(
    { range, onClose, query, editor, roles }: MentionsProps,
    ref
): JSX.Element | null {
    const { meFirstMembers } = useValues(membersLogic)

    // We start with 1 because the first item is the text controls
    const [selectedIndex, setSelectedIndex] = useState(0)
    const [selectedHorizontalIndex, setSelectedHorizontalIndex] = useState(0)

    const fuse = useMemo(() => {
        return createFuse(meFirstMembers, {
            keys: ['id', 'user.email', 'user.first_name', 'user.last_name'],
        })
    }, [meFirstMembers])

    const rolesFuse = useMemo(() => createFuse(roles ?? [], { keys: ['name'] }), [roles])

    const filteredOptions = useMemo((): MentionOption[] => {
        const members = query ? fuse.search(query).map((result) => result.item) : meFirstMembers
        const matchingRoles = query ? rolesFuse.search(query).map((result) => result.item) : (roles ?? [])
        return [
            ...members.map((member): MentionOption => ({ kind: 'member', member })),
            ...matchingRoles.map((role): MentionOption => ({ kind: 'role', role })),
        ]
    }, [query, fuse, meFirstMembers, rolesFuse, roles])

    useEffect(() => {
        setSelectedIndex(0)
        setSelectedHorizontalIndex(0)
    }, [query])

    const execute = async (option: MentionOption | undefined): Promise<void> => {
        if (editor && option) {
            editor
                .chain()
                .focus()
                .deleteRange(range)
                .insertContentAt(range.from, [
                    {
                        type: RichContentNodeType.Mention,
                        attrs:
                            option.kind === 'role'
                                ? { id: option.role.id, kind: 'role' }
                                : { id: option.member.user.id },
                    },
                ])
                .run()

            onClose?.()
        }
    }

    const onPressEnter = (): boolean => {
        const option = filteredOptions[selectedIndex]
        // No match (e.g. members still loading or no results) — let the editor
        // handle Enter normally instead of swallowing it.
        if (!option) {
            return false
        }
        void execute(option)
        return true
    }
    const onPressUp = (): boolean => {
        const count = filteredOptions.length
        if (count === 0) {
            return true
        }
        setSelectedIndex((selectedIndex - 1 + count) % count)
        return true
    }
    const onPressDown = (): boolean => {
        const count = filteredOptions.length
        if (count === 0) {
            return true
        }
        setSelectedIndex((selectedIndex + 1) % count)
        return true
    }

    const onKeyDown = useCallback(
        (event: KeyboardEvent): boolean => {
            const keyMappings = {
                ArrowUp: onPressUp,
                ArrowDown: onPressDown,
                Enter: onPressEnter,
            }

            if (isKeyOf(event.key, keyMappings)) {
                return keyMappings[event.key]()
            }

            return false
        },
        // oxlint-disable-next-line exhaustive-deps
        [selectedIndex, selectedHorizontalIndex, filteredOptions]
    )

    // Expose the keydown handler to the tiptap extension
    useImperativeHandle(ref, () => ({ onKeyDown }), [onKeyDown])

    if (!editor) {
        return null
    }

    return (
        <div className="deprecated-space-y-px">
            {filteredOptions.map((option, index) =>
                option.kind === 'member' ? (
                    <LemonButton
                        key={option.member.id}
                        fullWidth
                        icon={<ProfilePicture user={option.member.user} size="sm" />}
                        active={index === selectedIndex}
                        onClick={() => void execute(option)}
                    >
                        <span className="ph-no-capture">{`${option.member.user.first_name} <${option.member.user.email}>`}</span>
                    </LemonButton>
                ) : (
                    <LemonButton
                        key={option.role.id}
                        fullWidth
                        icon={<IconPeople />}
                        active={index === selectedIndex}
                        onClick={() => void execute(option)}
                    >
                        <span className="ph-no-capture">{option.role.name}</span>
                    </LemonButton>
                )
            )}

            {filteredOptions.length === 0 && (
                <div className="text-secondary p-1">
                    No {roles ? 'member or role' : 'member'} matching <code>@{query}</code>
                </div>
            )}
        </div>
    )
})

// Mounts mentionRolesLogic only where roles are offered, so a members-only editor never loads them.
const MentionsWithRoles = forwardRef<MentionsRef, MentionsProps>(function MentionsWithRoles(props, ref) {
    const { roles } = useValues(mentionRolesLogic)
    const { ensureRolesLoaded } = useActions(mentionRolesLogic)
    // Each `@` opens the picker again, which retries a failed roles load.
    useEffect(() => {
        ensureRolesLoaded()
    }, [ensureRolesLoaded])
    return <Mentions ref={ref} {...props} roles={roles} />
})

const MentionsPopover = forwardRef<MentionsRef, MentionsPopoverProps>(function MentionsPopover(
    { visible = true, decorationNode, children, onClose, includeRoles, ...props }: MentionsPopoverProps,
    ref
): JSX.Element | null {
    return (
        <Popover
            placement="bottom-start"
            fallbackPlacements={['top-start', 'right-start']}
            overlay={
                includeRoles ? (
                    <MentionsWithRoles ref={ref} onClose={onClose} {...props} />
                ) : (
                    <Mentions ref={ref} onClose={onClose} {...props} />
                )
            }
            referenceElement={decorationNode}
            visible={visible}
            onClickOutside={onClose}
        >
            {children}
        </Popover>
    )
})

const MentionsPluginKey = new PluginKey('mentions')

export const MentionsExtension = Extension.create<{ includeRoles: boolean }>({
    name: 'mentions',

    addOptions() {
        return { includeRoles: false }
    },

    addProseMirrorPlugins() {
        const includeRoles = this.options.includeRoles
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
                                props: { ...props, includeRoles },
                                editor: props.editor,
                            })
                        },

                        onUpdate(props) {
                            renderer.updateProps({ ...props, includeRoles })

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
