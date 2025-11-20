import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { createRef } from 'react'

import { IconImage } from '@posthog/icons'
import { LemonButton, LemonFileInput, LemonModal } from '@posthog/lemon-ui'

import { useUploadFiles } from 'lib/hooks/useUploadFiles'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { DefinitionLogicProps, definitionLogic } from 'scenes/data-management/definition/definitionLogic'

import { ObjectMediaPreview } from '~/types'

export function MediaPreviewModal({ props }: { props: DefinitionLogicProps }): JSX.Element {
    const logic = definitionLogic(props)
    const { isPreviewModalOpen, previews, previewsLoading, preview } = useValues(logic)
    const { setPreviewModalOpen, selectPreview, createMediaPreview } = useActions(logic)

    const { setFilesToUpload, filesToUpload, uploading } = useUploadFiles({
        onUpload: (_url, _fileName, uploadedMediaId) => {
            createMediaPreview(uploadedMediaId)
        },
        onError: (detail) => {
            lemonToast.error(`Error uploading image: ${detail}`)
        },
    })

    const mediaPreviewDragTarget = createRef<HTMLDivElement>()

    return (
        <LemonModal
            isOpen={isPreviewModalOpen}
            onClose={() => setPreviewModalOpen(false)}
            title="Upload preview image for the event"
            description="Choose from existing screenshots of the pages where event was triggered or upload your own"
            width={600}
        >
            <div className="flex flex-col gap-4">
                <div
                    ref={mediaPreviewDragTarget}
                    className="border-2 border-dashed rounded p-4 flex items-center justify-center cursor-pointer"
                    onClick={(e) => {
                        if (e.target === e.currentTarget) {
                            const input = mediaPreviewDragTarget.current?.querySelector(
                                'input[type="file"]'
                            ) as HTMLInputElement
                            input?.click()
                        }
                    }}
                >
                    <LemonFileInput
                        accept="image/*"
                        multiple={false}
                        onChange={setFilesToUpload}
                        loading={uploading}
                        value={filesToUpload}
                        alternativeDropTargetRef={mediaPreviewDragTarget}
                        callToAction={
                            <div className="flex items-center gap-2">
                                <IconImage />
                                <span>+ Upload yours</span>
                            </div>
                        }
                    />
                </div>

                <div className="grid grid-cols-3 gap-4 max-h-96 overflow-y-auto p-1">
                    {previews.map((item: ObjectMediaPreview) => (
                        <div
                            key={item.id}
                            className={clsx(
                                'relative border rounded cursor-pointer overflow-hidden group aspect-video bg-gray-100 flex items-center justify-center',
                                preview?.id === item.id
                                    ? 'border-accent'
                                    : 'border-transparent hover:border-primary-light'
                            )}
                            onClick={() => selectPreview(item)}
                        >
                            <img src={item.media_url} alt="Preview" className="max-w-full max-h-full object-contain" />
                        </div>
                    ))}
                    {previews.length === 0 && !previewsLoading && (
                        <div className="col-span-3 text-center text-muted p-4">No existing previews available</div>
                    )}
                </div>
            </div>
            <div className="flex justify-end mt-4">
                <LemonButton type="secondary" onClick={() => setPreviewModalOpen(false)}>
                    Close
                </LemonButton>
            </div>
        </LemonModal>
    )
}
