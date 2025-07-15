import { useValues } from 'kea'
import { TextContent } from 'lib/components/Cards/TextCard/TextCard'
import { useUploadFiles } from 'lib/hooks/useUploadFiles'
import { IconMarkdown, IconUploadFile } from 'lib/lemon-ui/icons'
import { LemonFileInput } from 'lib/lemon-ui/LemonFileInput'
import { LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { LemonTextArea, LemonTextAreaProps } from 'lib/lemon-ui/LemonTextArea/LemonTextArea'
import { lemonToast } from 'lib/lemon-ui/LemonToast'
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
                                    rightFooter={
                                        <>
                                            <Tooltip title="Markdown formatting supported">
                                                <div>
                                                    <IconMarkdown className="text-xl" />
                                                </div>
                                            </Tooltip>
                                        </>
                                    }
                                    actions={[
                                        <LemonFileInput
                                            key="file-upload"
                                            accept={'image/*'}
                                            multiple={false}
                                            alternativeDropTargetRef={dropRef}
                                            onChange={setFilesToUpload}
                                            loading={uploading}
                                            value={filesToUpload}
                                            callToAction={
                                                objectStorageAvailable ? (
                                                    <Tooltip title="Click here or drag and drop to upload images">
                                                        <div className="rounded hover:bg-fill-button-tertiary-hover px-1 py-0.5">
                                                            {' '}
                                                            <IconUploadFile className="text-xl" />
                                                        </div>
                                                    </Tooltip>
                                                ) : (
                                                    <Tooltip title="Enable object storage to add images by dragging and dropping">
                                                        <div className="rounded px-1 py-0.5">
                                                            {' '}
                                                            <IconUploadFile className="text-xl" />
                                                        </div>
                                                    </Tooltip>
                                                )
                                            }
                                        />,
                                    ]}
                                />
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
