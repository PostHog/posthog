import './LemonTextArea.scss'
import React, { createRef, useRef, useState } from 'react'
import clsx from 'clsx'
import TextareaAutosize from 'react-textarea-autosize'
import { IconMarkdown, IconTools } from 'lib/lemon-ui/icons'
import { TextContent } from 'lib/components/Cards/TextCard/TextCard'
import { lemonToast } from 'lib/lemon-ui/lemonToast'
import posthog from 'posthog-js'
import { LemonFileInput, useUploadFiles } from 'lib/lemon-ui/LemonFileInput/LemonFileInput'
import { useValues } from 'kea'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { Link } from 'lib/lemon-ui/Link'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { LemonTabs } from '../LemonTabs'

export interface LemonTextAreaProps
    extends Pick<
        React.TextareaHTMLAttributes<HTMLTextAreaElement>,
        'onFocus' | 'onBlur' | 'maxLength' | 'autoFocus' | 'onKeyDown'
    > {
    id?: string
    value?: string
    defaultValue?: string
    placeholder?: string
    className?: string
    /** Whether input field is disabled */
    disabled?: boolean
    ref?: React.Ref<HTMLTextAreaElement>
    onChange?: (newValue: string) => void
    /** Callback called when Cmd + Enter (or Ctrl + Enter) is pressed.
     * This checks for Cmd/Ctrl, as opposed to LemonInput, to avoid blocking multi-line input. */
    onPressCmdEnter?: (newValue: string) => void
    minRows?: number
    maxRows?: number
    rows?: number
}

/** A `textarea` component for multi-line text. */
export const LemonTextArea = React.forwardRef<HTMLTextAreaElement, LemonTextAreaProps>(function _LemonTextArea(
    { className, onChange, onPressCmdEnter: onPressEnter, minRows = 3, onKeyDown, ...textProps },
    ref
): JSX.Element {
    const _ref = useRef<HTMLTextAreaElement | null>(null)
    const textRef = ref || _ref

    return (
        <TextareaAutosize
            minRows={minRows}
            ref={textRef}
            className={clsx('LemonTextArea', className)}
            onKeyDown={(e) => {
                if (onPressEnter && e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
                    onPressEnter(textProps.value?.toString() ?? '')
                }

                onKeyDown?.(e)
            }}
            onChange={(event) => onChange?.(event.currentTarget.value ?? '')}
            {...textProps}
        />
    )
})

interface LemonTextMarkdownProps {
    value?: string
    onChange?: (s: string) => void
    placeholder?: string
    'data-attr'?: string
}

export function LemonTextMarkdown({ value, onChange, ...editAreaProps }: LemonTextMarkdownProps): JSX.Element {
    const { objectStorageAvailable } = useValues(preflightLogic)

    const [isPreviewShown, setIsPreviewShown] = useState(false)
    const dropRef = createRef<HTMLDivElement>()
    const textAreaRef = useRef<HTMLTextAreaElement>(null)

    const { setFilesToUpload, filesToUpload, uploading } = useUploadFiles({
        onUpload: (url, fileName) => {
            onChange?.(value + `\n\n![${fileName}](${url})`)
            posthog.capture('markdown image uploaded', { name: fileName })
        },
        onError: (detail) => {
            posthog.capture('markdown image upload failed', { error: detail })
            lemonToast.error(`Error uploading image: ${detail}`)
        },
    })

    return (
        <LemonTabs
            activeKey={isPreviewShown ? 'preview' : 'write'}
            onChange={(key) => setIsPreviewShown(key === 'preview')}
            tabs={[
                {
                    key: 'write',
                    label: 'Write',
                    content: (
                        <div ref={dropRef} className="LemonTextMarkdown flex flex-col space-y-1 rounded">
                            <LemonTextArea
                                ref={textAreaRef}
                                {...editAreaProps}
                                autoFocus
                                value={value}
                                onChange={onChange}
                            />
                            <div className="text-muted inline-flex items-center space-x-1">
                                <IconMarkdown className={'text-2xl'} />
                                <span>Markdown formatting support</span>
                            </div>
                            {objectStorageAvailable ? (
                                <LemonFileInput
                                    accept={'image/*'}
                                    multiple={false}
                                    alternativeDropTargetRef={dropRef}
                                    onChange={setFilesToUpload}
                                    loading={uploading}
                                    value={filesToUpload}
                                />
                            ) : (
                                <div className="text-muted inline-flex items-center space-x-1">
                                    <Tooltip title={'Enable object storage to add images by dragging and dropping.'}>
                                        <IconTools className={'text-xl mr-1'} />
                                    </Tooltip>
                                    <span>
                                        Add external images using{' '}
                                        <Link to={'https://www.markdownguide.org/basic-syntax/#images-1'}>
                                            {' '}
                                            Markdown image links
                                        </Link>
                                        .
                                    </span>
                                </div>
                            )}
                        </div>
                    ),
                },
                {
                    key: 'preview',
                    label: 'Preview',
                    content: value ? <TextContent text={value} /> : <i>Nothing to preview</i>,
                },
            ]}
        />
    )
}
