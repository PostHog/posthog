import './StepContentEditor.scss'

import { JSONContent } from '@tiptap/core'
import { Image } from '@tiptap/extension-image'
import { Link } from '@tiptap/extension-link'
import { Placeholder } from '@tiptap/extension-placeholder'
import { TextAlign } from '@tiptap/extension-text-align'
import { Underline } from '@tiptap/extension-underline'
import { EditorContent, useEditor } from '@tiptap/react'
import StarterKit from '@tiptap/starter-kit'
import posthog from 'posthog-js'
import { useCallback, useEffect, useRef, useState } from 'react'

import { IconCode, IconImage, IconList, IconVideoCamera } from '@posthog/icons'
import { LemonButton, LemonDivider, LemonInput, LemonMenu, LemonModal } from '@posthog/lemon-ui'

import { useUploadFiles } from 'lib/hooks/useUploadFiles'
import { LemonFileInput } from 'lib/lemon-ui/LemonFileInput'
import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { Popover } from 'lib/lemon-ui/Popover'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { IconBold, IconItalic, IconLink } from 'lib/lemon-ui/icons'

import { CodeBlockExtension } from './CodeBlockExtension'
import { EmbedExtension } from './EmbedExtension'
import { SlashCommandExtension } from './SlashCommandMenu'
import { IconAlignCenter, IconAlignLeft, IconAlignRight, IconListNumbers, IconUnderline } from './icons'

export interface StepContentEditorProps {
    content: JSONContent | null
    onChange: (content: JSONContent) => void
    placeholder?: string
    autoFocus?: boolean
    /** Custom image upload function. If not provided, uses the default PostHog API upload. Used for Toolbar uploads. */
    uploadImage?: (file: File) => Promise<{ url: string; fileName: string }>
    // restrict to only inline styles - no images/videos/etc
    inlineOnly?: boolean
}

const DEFAULT_CONTENT: JSONContent = {
    type: 'doc',
    content: [
        {
            type: 'paragraph',
        },
    ],
}

export function StepContentEditor({
    content,
    onChange,
    placeholder = "Type '/' for commands...",
    autoFocus = false,
    uploadImage,
    inlineOnly = false,
}: StepContentEditorProps): JSX.Element {
    const dropRef = useRef<HTMLDivElement>(null)
    const [linkUrl, setLinkUrl] = useState('')
    const [showLinkPopover, setShowLinkPopover] = useState(false)
    const [showVideoModal, setShowVideoModal] = useState(false)
    const [videoUrl, setVideoUrl] = useState('')
    const linkButtonRef = useRef<HTMLButtonElement>(null)
    // Force re-render when editor selection changes so toolbar active states update
    const [, setEditorState] = useState(0)
    const [customUploading, setCustomUploading] = useState(false)

    const editor = useEditor({
        extensions: inlineOnly
            ? [
                  StarterKit.configure({
                      heading: false,
                      codeBlock: false,
                      blockquote: false,
                      bulletList: false,
                      orderedList: false,
                      horizontalRule: false,
                  }),
                  Underline,
                  Placeholder.configure({
                      placeholder,
                  }),
              ]
            : [
                  StarterKit.configure({
                      heading: {
                          levels: [1, 2, 3],
                      },
                      codeBlock: false,
                  }),
                  CodeBlockExtension,
                  TextAlign.configure({
                      types: ['heading', 'paragraph'],
                  }),
                  Link.configure({
                      openOnClick: false,
                      HTMLAttributes: {
                          class: 'step-content-link',
                      },
                  }),
                  Image.configure({
                      HTMLAttributes: {
                          class: 'step-content-image',
                      },
                      allowBase64: true,
                  }),
                  Underline,
                  Placeholder.configure({
                      placeholder,
                  }),
                  EmbedExtension,
                  SlashCommandExtension,
              ],
        content: content || DEFAULT_CONTENT,
        autofocus: autoFocus,
        onUpdate: ({ editor: e }) => {
            onChange(e.getJSON())
        },
        onSelectionUpdate: () => {
            setEditorState((n) => n + 1)
        },
        onTransaction: () => {
            setEditorState((n) => n + 1)
        },
    })

    const defaultUpload = useUploadFiles({
        onUpload: (url, fileName) => {
            if (editor) {
                editor.chain().focus().setImage({ src: url, alt: fileName }).run()
            }
            posthog.capture('product tour image uploaded', { name: fileName })
        },
        onError: (detail) => {
            lemonToast.error(`Error uploading image: ${detail}`)
        },
    })

    const handleFileUpload = useCallback(
        async (files: File[]): Promise<void> => {
            if (files.length === 0) {
                return
            }
            const file = files[0]

            if (uploadImage) {
                setCustomUploading(true)
                try {
                    const { url, fileName } = await uploadImage(file)
                    if (editor) {
                        editor.chain().focus().setImage({ src: url, alt: fileName }).run()
                    }
                    posthog.capture('product tour image uploaded', { name: fileName })
                } catch (error) {
                    const detail = (error as Error).message || 'Upload failed'
                    lemonToast.error(`Error uploading image: ${detail}`)
                } finally {
                    setCustomUploading(false)
                }
            } else {
                defaultUpload.setFilesToUpload(files)
            }
        },
        [uploadImage, editor, defaultUpload.setFilesToUpload] // oxlint-disable-line react-hooks/exhaustive-deps
    )

    const uploading = uploadImage ? customUploading : defaultUpload.uploading

    useEffect(() => {
        const handleInsertImage = (): void => {
            const input = document.createElement('input')
            input.type = 'file'
            input.accept = 'image/*'
            input.onchange = (e) => {
                const file = (e.target as HTMLInputElement).files?.[0]
                if (file) {
                    void handleFileUpload([file])
                }
            }
            input.click()
        }

        window.addEventListener('product-tour-editor:insert-image', handleInsertImage)
        return () => window.removeEventListener('product-tour-editor:insert-image', handleInsertImage)
    }, [handleFileUpload])

    useEffect(() => {
        const handleInsertVideo = (): void => {
            setShowVideoModal(true)
        }

        window.addEventListener('product-tour-editor:insert-video', handleInsertVideo)
        return () => window.removeEventListener('product-tour-editor:insert-video', handleInsertVideo)
    }, [])

    useEffect(() => {
        if (editor && content) {
            const currentContent = editor.getJSON()
            if (JSON.stringify(currentContent) !== JSON.stringify(content)) {
                editor.commands.setContent(content)
            }
        }
    }, [editor, content])

    const setLink = (): void => {
        if (!linkUrl) {
            return
        }
        editor?.chain().focus().setLink({ href: linkUrl }).run()
        setShowLinkPopover(false)
        setLinkUrl('')
    }

    const removeLink = (): void => {
        editor?.chain().focus().unsetLink().run()
        setShowLinkPopover(false)
        setLinkUrl('')
    }

    const openLinkPopover = (): void => {
        const previousUrl = editor?.getAttributes('link').href || ''
        setLinkUrl(previousUrl)
        setShowLinkPopover(true)
    }

    const hasExistingLink = editor?.isActive('link') ?? false

    const insertEmbed = (): void => {
        if (!videoUrl || !editor) {
            return
        }
        editor.chain().focus().setEmbed({ src: videoUrl }).run()
        setShowVideoModal(false)
        setVideoUrl('')
    }

    if (!editor) {
        return <div className="StepContentEditor loading">Loading editor...</div>
    }

    const toolbar = (
        <div className="StepContentEditor__format-toolbar">
            {!inlineOnly && (
                <>
                    <LemonButton
                        size="small"
                        active={editor.isActive('heading', { level: 1 })}
                        onClick={() => editor.chain().focus().toggleHeading({ level: 1 }).run()}
                        tooltip="Heading 1"
                    >
                        H1
                    </LemonButton>
                    <LemonButton
                        size="small"
                        active={editor.isActive('heading', { level: 2 })}
                        onClick={() => editor.chain().focus().toggleHeading({ level: 2 }).run()}
                        tooltip="Heading 2"
                    >
                        H2
                    </LemonButton>
                    <LemonButton
                        size="small"
                        active={editor.isActive('heading', { level: 3 })}
                        onClick={() => editor.chain().focus().toggleHeading({ level: 3 }).run()}
                        tooltip="Heading 3"
                    >
                        H3
                    </LemonButton>
                    <LemonDivider vertical className="mx-1 self-stretch" />
                </>
            )}

            <LemonButton
                size="small"
                active={editor.isActive('bold')}
                onClick={() => editor.chain().focus().toggleBold().run()}
                icon={<IconBold />}
                tooltip="Bold"
            />
            <LemonButton
                size="small"
                active={editor.isActive('italic')}
                onClick={() => editor.chain().focus().toggleItalic().run()}
                icon={<IconItalic />}
                tooltip="Italic"
            />
            <LemonButton
                size="small"
                active={editor.isActive('underline')}
                onClick={() => editor.chain().focus().toggleUnderline().run()}
                icon={<IconUnderline />}
                tooltip="Underline"
            />
            <LemonButton
                size="small"
                active={editor.isActive('code')}
                onClick={() => editor.chain().focus().toggleCode().run()}
                icon={<IconCode />}
                tooltip="Inline code"
            />
            {!inlineOnly && (
                <>
                    <LemonDivider vertical className="mx-1 self-stretch" />
                    <LemonMenu
                        items={[
                            {
                                label: 'Bullet list',
                                icon: <IconList />,
                                onClick: () => editor.chain().focus().toggleBulletList().run(),
                                active: editor.isActive('bulletList'),
                            },
                            {
                                label: 'Numbered list',
                                icon: <IconListNumbers />,
                                onClick: () => editor.chain().focus().toggleOrderedList().run(),
                                active: editor.isActive('orderedList'),
                            },
                        ]}
                    >
                        <LemonButton
                            size="small"
                            active={editor.isActive('bulletList') || editor.isActive('orderedList')}
                            icon={editor.isActive('orderedList') ? <IconListNumbers /> : <IconList />}
                            tooltip="Lists"
                        />
                    </LemonMenu>
                    <LemonMenu
                        items={[
                            {
                                label: 'Align left',
                                icon: <IconAlignLeft />,
                                onClick: () => editor.chain().focus().setTextAlign('left').run(),
                                active: editor.isActive({ textAlign: 'left' }),
                            },
                            {
                                label: 'Align center',
                                icon: <IconAlignCenter />,
                                onClick: () => editor.chain().focus().setTextAlign('center').run(),
                                active: editor.isActive({ textAlign: 'center' }),
                            },
                            {
                                label: 'Align right',
                                icon: <IconAlignRight />,
                                onClick: () => editor.chain().focus().setTextAlign('right').run(),
                                active: editor.isActive({ textAlign: 'right' }),
                            },
                        ]}
                    >
                        <LemonButton
                            size="small"
                            icon={
                                editor.isActive({ textAlign: 'center' }) ? (
                                    <IconAlignCenter />
                                ) : editor.isActive({ textAlign: 'right' }) ? (
                                    <IconAlignRight />
                                ) : (
                                    <IconAlignLeft />
                                )
                            }
                            tooltip="Text alignment"
                        />
                    </LemonMenu>
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
                            ref={linkButtonRef}
                            size="small"
                            active={editor.isActive('link')}
                            onClick={openLinkPopover}
                            icon={<IconLink />}
                            tooltip="Link"
                        />
                    </Popover>
                    <LemonDivider vertical className="mx-1 self-stretch" />
                    <LemonFileInput
                        accept="image/*"
                        multiple={false}
                        alternativeDropTargetRef={dropRef}
                        onChange={(files) => void handleFileUpload(files)}
                        loading={uploading}
                        showUploadedFiles={false}
                        callToAction={
                            <LemonButton
                                size="small"
                                icon={uploading ? <Spinner className="text-sm" textColored /> : <IconImage />}
                                tooltip="Upload image (or drag & drop)"
                            />
                        }
                    />
                    <LemonButton
                        size="small"
                        icon={<IconVideoCamera />}
                        tooltip="Embed video"
                        onClick={() => setShowVideoModal(true)}
                    />
                    <span className="text-xs text-muted ml-auto">
                        Type <code>/</code> for commands
                    </span>
                </>
            )}
        </div>
    )

    return (
        <div ref={inlineOnly ? undefined : dropRef} className="StepContentEditor">
            {toolbar}

            <EditorContent editor={editor} className="StepContentEditor__content" />

            {!inlineOnly && (
                <LemonModal
                    isOpen={showVideoModal}
                    onClose={() => {
                        setShowVideoModal(false)
                        setVideoUrl('')
                    }}
                    title="Embed video"
                    footer={
                        <>
                            <LemonButton
                                type="secondary"
                                onClick={() => {
                                    setShowVideoModal(false)
                                    setVideoUrl('')
                                }}
                            >
                                Cancel
                            </LemonButton>
                            <LemonButton
                                type="primary"
                                onClick={insertEmbed}
                                disabledReason={!videoUrl ? 'Enter a URL' : undefined}
                            >
                                Embed
                            </LemonButton>
                        </>
                    }
                >
                    <div className="space-y-2">
                        <p className="text-muted text-sm">Paste a YouTube, Vimeo, or Loom URL</p>
                        <LemonInput
                            placeholder="https://www.youtube.com/watch?v=..."
                            value={videoUrl}
                            onChange={setVideoUrl}
                            onPressEnter={insertEmbed}
                            autoFocus
                            fullWidth
                        />
                    </div>
                </LemonModal>
            )}
        </div>
    )
}
