import { EditorContent, useEditor, useEditorState } from '@tiptap/react'
import { useEffect, useRef, useState } from 'react'

import { LemonButton, LemonInput } from '@posthog/lemon-ui'

import 'lib/components/MarkdownEditor/shared/RichMarkdownEditor.scss'
import { IconBold, IconItalic, IconLink } from 'lib/lemon-ui/icons'
import { Popover } from 'lib/lemon-ui/Popover'

import { SURVEY_RICH_TEXT_EXTENSIONS, normalizeRichTextHtml } from './surveyRichText'

export function SurveyRichTextEditor({
    value,
    onChange,
}: {
    value: string
    onChange: (value: string) => void
}): JSX.Element {
    const [linkUrl, setLinkUrl] = useState('')
    const [showLinkPopover, setShowLinkPopover] = useState(false)
    // The editor keeps the first onUpdate callback, so read the latest onChange through a ref
    const onChangeRef = useRef(onChange)
    onChangeRef.current = onChange

    const editor = useEditor({
        extensions: SURVEY_RICH_TEXT_EXTENSIONS,
        content: value,
        onUpdate: ({ editor }) => onChangeRef.current(normalizeRichTextHtml(editor.getHTML())),
    })

    const active = useEditorState({
        editor,
        selector: ({ editor }) => ({
            bold: editor?.isActive('bold') ?? false,
            italic: editor?.isActive('italic') ?? false,
            underline: editor?.isActive('underline') ?? false,
            strike: editor?.isActive('strike') ?? false,
            link: editor?.isActive('link') ?? false,
        }),
    })

    useEffect(() => {
        if (editor && normalizeRichTextHtml(editor.getHTML()) !== value) {
            editor.commands.setContent(value, { emitUpdate: false })
        }
    }, [editor, value])

    const setLink = (): void => {
        if (linkUrl) {
            editor?.chain().focus().extendMarkRange('link').setLink({ href: linkUrl }).run()
        }
        setShowLinkPopover(false)
    }

    const removeLink = (): void => {
        editor?.chain().focus().extendMarkRange('link').unsetLink().run()
        setShowLinkPopover(false)
    }

    return (
        <div className="RichMarkdownEditor border rounded overflow-hidden bg-surface-primary">
            <div className="flex flex-wrap items-center gap-0.5 border-b p-1">
                <LemonButton
                    size="small"
                    active={active?.bold}
                    onClick={() => editor?.chain().focus().toggleBold().run()}
                    icon={<IconBold />}
                    tooltip="Bold"
                />
                <LemonButton
                    size="small"
                    active={active?.italic}
                    onClick={() => editor?.chain().focus().toggleItalic().run()}
                    icon={<IconItalic />}
                    tooltip="Italic"
                />
                <LemonButton
                    size="small"
                    active={active?.underline}
                    onClick={() => editor?.chain().focus().toggleUnderline().run()}
                    tooltip="Underline"
                >
                    <span className="font-semibold underline">U</span>
                </LemonButton>
                <LemonButton
                    size="small"
                    active={active?.strike}
                    onClick={() => editor?.chain().focus().toggleStrike().run()}
                    tooltip="Strikethrough"
                >
                    <span className="font-semibold line-through">S</span>
                </LemonButton>
                <Popover
                    visible={showLinkPopover}
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
                                {active?.link && (
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
                                    {active?.link ? 'Update' : 'Set'}
                                </LemonButton>
                            </div>
                        </div>
                    }
                >
                    <LemonButton
                        size="small"
                        active={active?.link}
                        icon={<IconLink />}
                        onClick={() => {
                            setLinkUrl(String(editor?.getAttributes('link').href ?? ''))
                            setShowLinkPopover(true)
                        }}
                        tooltip="Link"
                    />
                </Popover>
            </div>
            <EditorContent
                editor={editor}
                className="RichMarkdownEditor__content min-h-16 px-3 py-2"
                data-attr="survey-rich-text-editor"
            />
        </div>
    )
}
