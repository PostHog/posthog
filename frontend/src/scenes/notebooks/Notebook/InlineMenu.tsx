import { LemonInput } from '@posthog/lemon-ui'
import { Editor } from '@tiptap/core'
import { BubbleMenu } from '@tiptap/react'
import clsx from 'clsx'
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
            <div className="NotebookInlineMenu flex bg-white rounded border items-center text-muted-alt p-0.5">
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
                        <Option onClick={openLink} status="primary">
                            <IconOpenInNew />
                        </Option>
                        <Option onClick={() => editor.commands.unsetMark('link')} status="destructive">
                            <IconDelete />
                        </Option>
                    </>
                ) : (
                    <>
                        <Option onClick={() => editor.commands.toggleMark('bold')} active={editor.isActive('bold')}>
                            <IconBold />
                        </Option>
                        <Option onClick={() => editor.commands.toggleMark('italic')} active={editor.isActive('italic')}>
                            <IconItalic />
                        </Option>
                        <Option onClick={() => editor.commands.setMark('link')}>
                            <IconLink />
                        </Option>
                    </>
                )}
            </div>
        </BubbleMenu>
    )
}

const Option = ({
    status = 'default',
    active = false,
    children,
    onClick,
}: {
    status?: 'default' | 'primary' | 'destructive'
    active?: boolean
    children: JSX.Element
    onClick: () => void
}): JSX.Element => {
    return (
        <button
            type="button"
            className={clsx(
                'NotebookInlineMenu__Option',
                `NotebookInlineMenu__Option--${status}`,
                active && 'NotebookInlineMenu__Option--active'
            )}
            onClick={onClick}
        >
            {children}
        </button>
    )
}
