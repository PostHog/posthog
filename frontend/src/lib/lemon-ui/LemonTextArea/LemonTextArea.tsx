import './LemonTextArea.scss'

import clsx from 'clsx'
import { useValues } from 'kea'
import { TextContent } from 'lib/components/Cards/TextCard/TextCard'
import { useUploadFiles } from 'lib/hooks/useUploadFiles'
import { IconMarkdown, IconTools } from 'lib/lemon-ui/icons'
import { LemonFileInput } from 'lib/lemon-ui/LemonFileInput/LemonFileInput'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { Link } from 'lib/lemon-ui/Link'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import posthog from 'posthog-js'
import React, { createRef, useRef, useState } from 'react'
import TextareaAutosize from 'react-textarea-autosize'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'

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
    /** Whether to stop propagation of events from the input */
    stopPropagation?: boolean
}

/** A `textarea` component for multi-line text. */
export const LemonTextArea = React.forwardRef<HTMLTextAreaElement, LemonTextAreaProps>(function _LemonTextArea(
    { className, onChange, onPressCmdEnter: onPressEnter, minRows = 3, onKeyDown, stopPropagation, ...textProps },
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
                if (stopPropagation) {
                    e.stopPropagation()
                }
                if (onPressEnter && e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
                    onPressEnter(textProps.value?.toString() ?? '')
                }

                onKeyDown?.(e)
            }}
            onChange={(event) => {
                if (stopPropagation) {
                    event.stopPropagation()
                }
                return onChange?.(event.currentTarget.value ?? '')
            }}
            {...textProps}
        />
    )
})

interface LemonTextAreaMarkdownProps {
    value?: string
    onChange?: (s: string) => void
    placeholder?: string
    'data-attr'?: string
}

export function LemonTextAreaMarkdown({ value, onChange, ...editAreaProps }: LemonTextAreaMarkdownProps): JSX.Element {
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
                    content: value ? (
                        <TextContent text={value} className={'LemonTextArea--preview'} />
                    ) : (
                        <i>Nothing to preview</i>
                    ),
                },
            ]}
        />
    )
}
