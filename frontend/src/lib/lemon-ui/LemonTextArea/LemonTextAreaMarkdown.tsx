import { useValues } from 'kea'
import { TextContent } from 'lib/components/Cards/TextCard/TextCard'
import { useUploadFiles } from 'lib/hooks/useUploadFiles'
import { IconMarkdown, IconTools } from 'lib/lemon-ui/icons'
import { LemonFileInput } from 'lib/lemon-ui/LemonFileInput'
import { LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { LemonTextArea, LemonTextAreaProps } from 'lib/lemon-ui/LemonTextArea/LemonTextArea'
import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { Link } from 'lib/lemon-ui/Link'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import posthog from 'posthog-js'
import React, { useRef, useState } from 'react'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'

export const LemonTextAreaMarkdown = React.forwardRef<HTMLTextAreaElement, LemonTextAreaProps>(
    function LemonTextAreaMarkdown({ value, onChange, className, ...editAreaProps }, ref): JSX.Element {
        const { objectStorageAvailable } = useValues(preflightLogic)

        const [isPreviewShown, setIsPreviewShown] = useState(false)
        const dropRef = useRef<HTMLDivElement>(null)

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
                className={className}
                tabs={[
                    {
                        key: 'write',
                        label: 'Write',
                        content: (
                            <div ref={dropRef} className="LemonTextMarkdown flex flex-col gap-y-1 rounded">
                                <LemonTextArea
                                    ref={ref}
                                    {...editAreaProps}
                                    autoFocus
                                    value={value}
                                    onChange={onChange}
                                />
                                <div className="text-secondary inline-flex items-center gap-x-1">
                                    <IconMarkdown className="text-2xl" />
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
                                    <div className="text-secondary inline-flex items-center gap-x-1">
                                        <Tooltip title="Enable object storage to add images by dragging and dropping.">
                                            <span>
                                                <IconTools className="text-xl mr-1" />
                                            </span>
                                        </Tooltip>
                                        <span>
                                            Add external images using{' '}
                                            <Link to="https://www.markdownguide.org/basic-syntax/#images-1">
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
                            <TextContent text={value} className="LemonTextArea--preview" />
                        ) : (
                            <i>Nothing to preview</i>
                        ),
                    },
                ]}
            />
        )
    }
)
