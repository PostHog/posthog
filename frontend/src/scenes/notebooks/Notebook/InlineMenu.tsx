import { LemonButton, LemonInput } from '@posthog/lemon-ui'
import { Editor } from '@tiptap/core'
import { BubbleMenu } from '@tiptap/react'
import { IconBold, IconDelete, IconItalic, IconLink, IconOpenInNew } from 'lib/lemon-ui/icons'

export const InlineMenu = ({ editor }: { editor: Editor }): JSX.Element => {
    const { href, target } = editor.getAttributes('link')

    const setLink = (href: string): void => {
        editor.commands.setMark('link', { href: href })
    }

    const openLink = (): void => {
        window.open(href, target)
    }

    return (
        <BubbleMenu editor={editor} tippyOptions={{}}>
            <div className="NotebookInlineMenu flex bg-white rounded border items-center text-muted-alt p-1 space-x-1">
                {editor.isActive('link') ? (
                    <>
                        <LemonInput
                            size="small"
                            placeholder="https://posthog.com"
                            onChange={setLink}
                            value={href}
                            className="border-0"
                            autoFocus
                        />
                        <LemonButton onClick={openLink} icon={<IconOpenInNew />} status="primary" size="small" />
                        <LemonButton
                            onClick={() => editor.chain().focus().unsetMark('link').run()}
                            icon={<IconDelete />}
                            status="danger"
                            size="small"
                        />
                    </>
                ) : (
                    <>
                        <LemonButton
                            onClick={() => editor.chain().focus().toggleMark('bold').run()}
                            active={editor.isActive('bold')}
                            icon={<IconBold />}
                            size="small"
                            status={editor.isActive('bold') ? 'primary' : 'stealth'}
                        />
                        <LemonButton
                            onClick={() => editor.chain().focus().toggleMark('italic').run()}
                            active={editor.isActive('italic')}
                            icon={<IconItalic />}
                            status={editor.isActive('italic') ? 'primary' : 'stealth'}
                            size="small"
                        />
                        <LemonButton
                            onClick={() => editor.chain().focus().setMark('link').run()}
                            icon={<IconLink />}
                            status="stealth"
                            size="small"
                        />
                    </>
                )}
            </div>
        </BubbleMenu>
    )
}
