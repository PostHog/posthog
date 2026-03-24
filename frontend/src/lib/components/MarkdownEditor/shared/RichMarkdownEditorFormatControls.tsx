import { Editor } from '@tiptap/core'

import { IconCode, IconList, IconMinus } from '@posthog/icons'
import { LemonButton, LemonDivider, LemonInput, LemonMenu } from '@posthog/lemon-ui'

import { IconBold, IconItalic, IconLink, IconTextSize } from 'lib/lemon-ui/icons'
import { Popover } from 'lib/lemon-ui/Popover'

function getHeadingTriggerContent(editor: Editor | null): JSX.Element | string {
    if (editor?.isActive('heading', { level: 1 })) {
        return 'H1'
    }
    if (editor?.isActive('heading', { level: 2 })) {
        return 'H2'
    }
    if (editor?.isActive('heading', { level: 3 })) {
        return 'H3'
    }
    return <IconTextSize className="size-[1.125rem]" />
}

function isTextOrHeadingBlockActive(editor: Editor | null): boolean {
    if (!editor) {
        return false
    }
    return (
        editor.isActive('paragraph') ||
        editor.isActive('heading', { level: 1 }) ||
        editor.isActive('heading', { level: 2 }) ||
        editor.isActive('heading', { level: 3 })
    )
}

export type RichMarkdownEditorFormatControlsProps = {
    editor: Editor | null
    linkUrl: string
    setLinkUrl: (url: string) => void
    showLinkPopover: boolean
    setShowLinkPopover: (visible: boolean) => void
    /**
     * When set (e.g. after **Link** from `/` slash), positions the link popover on this node instead of the toolbar button.
     */
    linkPopoverReferenceElement?: HTMLElement | null
    /** Reset external reference (slash); call when opening the popover from the link toolbar button. */
    clearLinkPopoverReference?: () => void
}

export function RichMarkdownEditorFormatControls({
    editor,
    linkUrl,
    setLinkUrl,
    showLinkPopover,
    setShowLinkPopover,
    linkPopoverReferenceElement = null,
    clearLinkPopoverReference,
}: RichMarkdownEditorFormatControlsProps): JSX.Element {
    const hasExistingLink = editor?.isActive('link') ?? false

    const setLink = (): void => {
        if (!linkUrl || !editor) {
            return
        }
        editor.chain().focus().setLink({ href: linkUrl }).run()
        setShowLinkPopover(false)
        setLinkUrl('')
    }

    const removeLink = (): void => {
        editor?.chain().focus().unsetLink().run()
        setShowLinkPopover(false)
        setLinkUrl('')
    }

    const openLinkPopover = (): void => {
        clearLinkPopoverReference?.()
        const previousUrl = editor?.getAttributes('link').href || ''
        setLinkUrl(String(previousUrl ?? ''))
        setShowLinkPopover(true)
    }

    return (
        <div className="flex items-center gap-0.5">
            <LemonMenu
                items={[
                    {
                        label: 'Text',
                        onClick: () => editor?.chain().focus().setParagraph().run(),
                        active: !!(editor?.isActive('paragraph') && !editor.isActive('heading')),
                    },
                    {
                        label: 'Heading 1',
                        onClick: () => editor?.chain().focus().toggleHeading({ level: 1 }).run(),
                        active: !!editor?.isActive('heading', { level: 1 }),
                    },
                    {
                        label: 'Heading 2',
                        onClick: () => editor?.chain().focus().toggleHeading({ level: 2 }).run(),
                        active: !!editor?.isActive('heading', { level: 2 }),
                    },
                    {
                        label: 'Heading 3',
                        onClick: () => editor?.chain().focus().toggleHeading({ level: 3 }).run(),
                        active: !!editor?.isActive('heading', { level: 3 }),
                    },
                ]}
            >
                <LemonButton size="small" active={isTextOrHeadingBlockActive(editor)} tooltip="Text and headings">
                    {getHeadingTriggerContent(editor)}
                </LemonButton>
            </LemonMenu>
            <LemonDivider vertical className="mx-1 self-stretch" />
            <LemonButton
                size="small"
                active={editor?.isActive('bold')}
                onClick={() => editor?.chain().focus().toggleBold().run()}
                icon={<IconBold />}
                tooltip="Bold"
            />
            <LemonButton
                size="small"
                active={editor?.isActive('italic')}
                onClick={() => editor?.chain().focus().toggleItalic().run()}
                icon={<IconItalic />}
                tooltip="Italic"
            />
            <LemonButton
                size="small"
                active={editor?.isActive('underline')}
                onClick={() => editor?.chain().focus().toggleUnderline().run()}
                tooltip="Underline"
            >
                <span className="font-semibold underline">U</span>
            </LemonButton>
            <LemonButton
                size="small"
                active={editor?.isActive('strike')}
                onClick={() => editor?.chain().focus().toggleStrike().run()}
                tooltip="Strikethrough"
            >
                <span className="font-semibold line-through">S</span>
            </LemonButton>
            <LemonButton
                size="small"
                active={editor?.isActive('code')}
                onClick={() => editor?.chain().focus().toggleCode().run()}
                icon={<IconCode />}
                tooltip="Inline code"
            />
            <LemonButton
                size="small"
                active={editor?.isActive('codeBlock')}
                onClick={() => editor?.chain().focus().toggleCodeBlock().run()}
                tooltip="Code block"
            >
                {`</>`}
            </LemonButton>
            <LemonButton
                size="small"
                active={editor?.isActive('blockquote')}
                onClick={() => editor?.chain().focus().toggleBlockquote().run()}
                tooltip="Blockquote"
            >
                "
            </LemonButton>
            <LemonButton
                size="small"
                icon={<IconMinus />}
                onClick={() => editor?.chain().focus().setHorizontalRule().run()}
                tooltip="Horizontal divider"
            />
            <LemonDivider vertical className="mx-1 self-stretch" />
            <LemonMenu
                items={[
                    {
                        label: 'Bullet list',
                        icon: <IconList />,
                        onClick: () => editor?.chain().focus().toggleBulletList().run(),
                        active: !!editor?.isActive('bulletList'),
                    },
                    {
                        label: 'Numbered list',
                        icon: <span className="inline-flex w-4 justify-center text-xs font-semibold">1.</span>,
                        onClick: () => editor?.chain().focus().toggleOrderedList().run(),
                        active: !!editor?.isActive('orderedList'),
                    },
                    {
                        label: 'Task list',
                        icon: <span className="inline-flex w-4 justify-center text-xs">[ ]</span>,
                        onClick: () => editor?.chain().focus().toggleTaskList().run(),
                        active: !!editor?.isActive('taskList'),
                    },
                ]}
            >
                <LemonButton
                    size="small"
                    active={
                        editor?.isActive('bulletList') ||
                        editor?.isActive('orderedList') ||
                        editor?.isActive('taskList')
                    }
                    icon={<IconList />}
                    tooltip="Lists"
                />
            </LemonMenu>
            <Popover
                key={
                    linkPopoverReferenceElement ? 'markdown-link-popover-external-ref' : 'markdown-link-popover-toolbar'
                }
                visible={showLinkPopover}
                referenceElement={linkPopoverReferenceElement ?? undefined}
                onClickOutside={() => setShowLinkPopover(false)}
                overlay={
                    <div className="p-2 flex flex-col gap-2 min-w-64">
                        <LemonInput
                            size="small"
                            placeholder="https://..."
                            value={linkUrl}
                            onChange={setLinkUrl}
                            onPressEnter={setLink}
                            autoFocus
                            fullWidth
                        />
                        <div className="flex gap-2 justify-end">
                            {hasExistingLink && (
                                <LemonButton size="small" status="danger" onClick={removeLink}>
                                    Remove
                                </LemonButton>
                            )}
                            <LemonButton
                                size="small"
                                type="primary"
                                onClick={setLink}
                                disabledReason={!linkUrl ? 'Enter a URL' : undefined}
                            >
                                {hasExistingLink ? 'Update' : 'Set'}
                            </LemonButton>
                        </div>
                    </div>
                }
            >
                <LemonButton
                    size="small"
                    active={editor?.isActive('link')}
                    icon={<IconLink />}
                    onClick={openLinkPopover}
                    tooltip="Link"
                />
            </Popover>
        </div>
    )
}
