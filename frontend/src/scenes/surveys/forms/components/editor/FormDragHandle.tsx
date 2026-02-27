import DragHandle from '@tiptap/extension-drag-handle-react'
import { Node as ProseMirrorNode } from '@tiptap/pm/model'
import { Editor } from '@tiptap/react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import { IconCopy, IconDrag, IconPlus, IconTrash } from '@posthog/icons'
import { LemonButton, LemonInput, LemonMenu, LemonMenuItem, LemonMenuItems, LemonSwitch } from '@posthog/lemon-ui'

import { QuestionTypeSetting, FormQuestion, SettingType } from '../../formTypes'
import { QUESTION_TYPE_REGISTRY } from '../questions/questionTypeRegistry'
import { parseQuestionData } from './nodes/FormQuestionNode'
import { SLASH_COMMANDS } from './SlashCommands'

function settingToMenuItem(setting: QuestionTypeSetting, onUpdate: (q: FormQuestion) => void): LemonMenuItem {
    switch (setting.type) {
        case SettingType.Toggle:
            return {
                label: () => (
                    <div
                        className="flex items-center justify-between gap-4 py-1 px-2 cursor-pointer"
                        onClick={(e) => {
                            e.stopPropagation()
                            onUpdate(setting.apply(!setting.checked))
                        }}
                    >
                        <span className="text-sm font-medium">{setting.label}</span>
                        <LemonSwitch checked={setting.checked} size="small" />
                    </div>
                ),
            }
        case SettingType.Select:
            return {
                label: setting.label,
                items: setting.options.map((opt) => ({
                    label: String(opt.label),
                    active: setting.value === opt.value,
                    onClick: () => onUpdate(setting.apply(opt.value)),
                })),
            }
        case SettingType.Input:
            return {
                label: () => (
                    <div className="flex flex-col gap-0.5 px-2 py-1" onClick={(e) => e.stopPropagation()}>
                        <span className="text-xs text-secondary">{setting.label}</span>
                        {setting.inputType === 'number' ? (
                            <LemonInput
                                size="small"
                                type="number"
                                value={Number(setting.value)}
                                placeholder={setting.placeholder}
                                onChange={(v) => onUpdate(setting.apply(v ?? 0))}
                            />
                        ) : (
                            <LemonInput
                                size="small"
                                value={String(setting.value)}
                                placeholder={setting.placeholder}
                                onChange={(v) => onUpdate(setting.apply(v))}
                            />
                        )}
                    </div>
                ),
            }
    }
}

function settingsToMenuItems(settings: QuestionTypeSetting[], onUpdate: (q: FormQuestion) => void): LemonMenuItem[] {
    return settings.flatMap((setting) => {
        const item = settingToMenuItem(setting, onUpdate)
        if (setting.type === SettingType.Toggle && setting.checked && setting.children) {
            return [item, ...settingsToMenuItems(setting.children, onUpdate)]
        }
        return [item]
    })
}

interface FormDragHandleProps {
    editor: Editor | null
}

export function FormDragHandle({ editor }: FormDragHandleProps): JSX.Element | null {
    const [currentNode, setCurrentNode] = useState<ProseMirrorNode | null>(null)
    const [currentPos, setCurrentPos] = useState(-1)
    const handleRef = useRef<HTMLDivElement>(null)
    const menuOpenRef = useRef(false)
    const draggingRef = useRef(false)

    useEffect(() => {
        if (!editor) {
            return
        }
        const dom = editor.view.dom

        const onDragStart = (): void => {
            draggingRef.current = true
        }
        const onDragSettled = (): void => {
            // Two RAFs lets the post-drop transaction and React re-render settle
            requestAnimationFrame(() => {
                requestAnimationFrame(() => {
                    draggingRef.current = false
                })
            })
        }

        dom.addEventListener('dragstart', onDragStart)
        dom.addEventListener('drop', onDragSettled)
        dom.addEventListener('dragend', onDragSettled)

        return () => {
            dom.removeEventListener('dragstart', onDragStart)
            dom.removeEventListener('drop', onDragSettled)
            dom.removeEventListener('dragend', onDragSettled)
        }
    }, [editor])

    const onNodeChange = useCallback(
        ({ node, pos }: { node: ProseMirrorNode | null; editor: Editor; pos: number }): void => {
            if (menuOpenRef.current || draggingRef.current) {
                return
            }
            if (handleRef.current) {
                handleRef.current.style.position = ''
                handleRef.current.style.top = ''
                handleRef.current.style.left = ''
            }
            const isTitleNode = pos === 0 && node?.type.name === 'heading'
            const isFormButtonNode = node?.type.name === 'formButton'
            const shouldHideHandle = isTitleNode || isFormButtonNode
            if (handleRef.current) {
                handleRef.current.style.display = shouldHideHandle ? 'none' : ''
            }
            setCurrentNode(shouldHideHandle ? null : node)
            setCurrentPos(shouldHideHandle ? -1 : pos)
        },
        []
    )

    const onVisibilityChange = useCallback(
        (visible: boolean): void => {
            menuOpenRef.current = visible
            if (visible) {
                if (handleRef.current) {
                    const rect = handleRef.current.getBoundingClientRect()
                    handleRef.current.style.position = 'fixed'
                    handleRef.current.style.top = `${rect.top}px`
                    handleRef.current.style.left = `${rect.left}px`
                }
                editor?.commands.lockDragHandle()
            } else {
                editor?.commands.unlockDragHandle()
            }
        },
        [editor]
    )

    const handleDuplicate = useCallback((): void => {
        if (!editor || !currentNode || currentPos < 0) {
            return
        }
        editor
            .chain()
            .focus()
            .insertContentAt(currentPos + currentNode.nodeSize, currentNode.toJSON())
            .run()
    }, [editor, currentNode, currentPos])

    const handleDelete = useCallback((): void => {
        if (!editor || !currentNode || currentPos < 0) {
            return
        }
        editor
            .chain()
            .focus()
            .deleteRange({ from: currentPos, to: currentPos + currentNode.nodeSize })
            .run()
    }, [editor, currentNode, currentPos])

    const updateQuestionData = useCallback(
        (updated: FormQuestion): void => {
            if (!editor || !currentNode || currentPos < 0) {
                return
            }
            const tr = editor.state.tr.setNodeMarkup(currentPos, undefined, {
                ...currentNode.attrs,
                questionData: JSON.stringify(updated),
            })
            editor.view.dispatch(tr)
            // Re-read the node so memoized menu items see fresh data
            const freshNode = editor.state.doc.nodeAt(currentPos)
            if (freshNode) {
                setCurrentNode(freshNode)
            }
        },
        [editor, currentNode, currentPos]
    )

    const insertMenuItems: LemonMenuItems = useMemo(() => {
        if (!editor) {
            return []
        }
        const formCommands = SLASH_COMMANDS.filter((c) => c.section === 'form')
        const contentCommands = SLASH_COMMANDS.filter((c) => c.section === 'content')

        return [
            {
                title: 'Form fields',
                items: formCommands.map((cmd) => ({
                    label: cmd.title,
                    icon: cmd.icon,
                    onClick: () => {
                        if (currentNode && currentPos >= 0) {
                            const endPos = currentPos + currentNode.nodeSize
                            editor
                                .chain()
                                .focus()
                                .insertContentAt(endPos, { type: 'paragraph' })
                                .setTextSelection(endPos + 1)
                                .run()
                            cmd.command(editor)
                        }
                    },
                })),
            },
            {
                title: 'Content',
                items: contentCommands.map((cmd) => ({
                    label: cmd.title,
                    icon: cmd.icon,
                    onClick: () => {
                        if (currentNode && currentPos >= 0) {
                            const endPos = currentPos + currentNode.nodeSize
                            editor
                                .chain()
                                .focus()
                                .insertContentAt(endPos, { type: 'paragraph' })
                                .setTextSelection(endPos + 1)
                                .run()
                            cmd.command(editor)
                        }
                    },
                })),
            },
        ]
    }, [editor, currentNode, currentPos])

    const contextMenuItems: LemonMenuItems = useMemo(() => {
        const items: LemonMenuItems = []

        if (currentNode?.type.name === 'formQuestion') {
            const questionData = parseQuestionData(currentNode.attrs.questionData)

            const registrySettings = QUESTION_TYPE_REGISTRY[questionData.type].settings?.(questionData) ?? []
            const allSettings: QuestionTypeSetting[] = [
                {
                    type: SettingType.Toggle,
                    label: 'Required',
                    checked: !questionData.optional,
                    apply: (checked) => ({ ...questionData, optional: !checked }),
                },
                ...registrySettings,
            ]

            items.push({
                title: 'Settings',
                items: settingsToMenuItems(allSettings, updateQuestionData),
            })
        }

        items.push({
            items: [
                {
                    label: 'Duplicate',
                    icon: <IconCopy />,
                    onClick: handleDuplicate,
                },
                {
                    label: 'Delete',
                    icon: <IconTrash />,
                    status: 'danger' as const,
                    onClick: handleDelete,
                },
            ],
        })

        return items
    }, [currentNode, handleDuplicate, handleDelete, updateQuestionData])

    if (!editor) {
        return null
    }

    return (
        <DragHandle editor={editor} onNodeChange={onNodeChange}>
            <div ref={handleRef} className="FormDragHandle">
                <LemonMenu items={insertMenuItems} placement="bottom-start" onVisibilityChange={onVisibilityChange}>
                    <LemonButton size="small" noPadding icon={<IconPlus />} className="FormDragHandle__plus" />
                </LemonMenu>
                <LemonMenu
                    items={contextMenuItems}
                    placement="bottom-start"
                    onVisibilityChange={onVisibilityChange}
                    className="min-w-48"
                >
                    <LemonButton
                        size="small"
                        noPadding
                        icon={<IconDrag />}
                        className="FormDragHandle__grip"
                        data-drag-handle
                    />
                </LemonMenu>
            </div>
        </DragHandle>
    )
}
