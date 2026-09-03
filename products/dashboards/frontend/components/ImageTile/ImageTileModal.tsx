import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { Field, Form } from 'kea-forms'
import posthog from 'posthog-js'
import { useEffect, useRef, useState } from 'react'
import type { KeyboardEvent, PointerEvent, RefObject } from 'react'

import { IconImage } from '@posthog/icons'

import { textCardConverter } from 'lib/components/Cards/TextCard/textCardMarkdown'
import { textCardModalLogic } from 'lib/components/Cards/TextCard/textCardModalLogic'
import type { TextCardModalProps } from 'lib/components/Cards/TextCard/textCardModalLogic'
import { useUploadFiles } from 'lib/hooks/useUploadFiles'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonFileInput } from 'lib/lemon-ui/LemonFileInput'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { LemonLabel } from 'lib/lemon-ui/LemonLabel'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { LemonSelect } from 'lib/lemon-ui/LemonSelect'
import { LemonSwitch } from 'lib/lemon-ui/LemonSwitch'
import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { preflightLogic } from 'lib/logic/preflightLogic'

import { DashboardTileIdOrNew, DashboardType, QueryBasedInsightModel } from '~/types'

import {
    DEFAULT_IMAGE_TILE_POSITION,
    getImageOnlyTextCardImage,
    imageTileToMarkdown,
    imageTilePositionToCss,
} from './imageTileUtils'
import type { ImageTileImage, ImageTilePosition } from './imageTileUtils'

const IMAGE_TILE_LAYOUT_OPTIONS = [
    { value: 'contain', label: 'Show full image' },
    { value: 'cover', label: 'Fill the tile' },
] satisfies { value: ImageTileImage['layout']; label: string }[]

interface ImagePreviewDragState {
    pointerId: number
    startClientX: number
    startClientY: number
    startPosition: ImageTilePosition
    previewWidth: number
    previewHeight: number
}

const IMAGE_TILE_HORIZONTAL_DRAG_FACTOR = 2
const IMAGE_TILE_POSITION_STEP = 10
const MAX_IMAGE_UPLOAD_SIZE_BYTES = 4 * 1024 * 1024
const IMAGE_UPLOAD_ERROR_MESSAGES = {
    NOT_AN_IMAGE: 'File is not an image',
    UNSUPPORTED_TYPE: 'This image format is not supported',
    TOO_LARGE: 'Image exceeds the maximum file size',
} as const
const SUPPORTED_IMAGE_UPLOAD_TYPES = ['image/png', 'image/jpeg', 'image/jpg', 'image/gif', 'image/webp', 'image/avif']

export function ImageTileModal({
    isOpen,
    onClose,
    dashboard,
    imageTileId,
}: {
    isOpen: boolean
    onClose: () => void
    dashboard: DashboardType<QueryBasedInsightModel>
    imageTileId: DashboardTileIdOrNew
}): JSX.Element {
    const isNewTile = imageTileId === null
    const modalLogicProps: TextCardModalProps = {
        dashboard,
        textTileId: imageTileId,
        onClose,
        tileType: 'image',
    }
    const modalLogic = textCardModalLogic(modalLogicProps)
    const { objectStorageAvailable } = useValues(preflightLogic)
    const { isTextTileSubmitting, textTile, textTileValidationErrors } = useValues(modalLogic)
    const { resetTextTile, setTextTileValues } = useActions(modalLogic)
    const previewRef = useRef<HTMLElement | null>(null)
    const fileInputRef = useRef<HTMLInputElement>(null)
    const previewDragRef = useRef<ImagePreviewDragState | null>(null)
    const imageRef = useRef<ImageTileImage | null>(null)
    const previewPositionRef = useRef<ImageTilePosition | null>(null)
    const imageOperationInProgressRef = useRef(false)
    const uploadRequestedRef = useRef(false)
    const [isDragging, setIsDragging] = useState(false)
    const [previewPosition, setPreviewPosition] = useState<ImageTilePosition | null>(null)
    const [uploadComplete, setUploadComplete] = useState(false)
    const image = getImageOnlyTextCardImage(textCardConverter, textTile.body)
    const previewImage = image && previewPosition ? { ...image, position: previewPosition } : image
    imageRef.current = image

    useEffect(() => {
        const previewPositionToCommit = previewPositionRef.current
        if (
            previewPositionToCommit &&
            image &&
            previewPositionToCommit.x === image.position.x &&
            previewPositionToCommit.y === image.position.y
        ) {
            previewPositionRef.current = null
            setPreviewPosition(null)
        }
    }, [image])

    const setPreviewRef = (element: HTMLElement | null): void => {
        previewRef.current = element
    }

    const { setFilesToUpload, filesToUpload, uploading } = useUploadFiles({
        onUpload: (url) => {
            const currentImage = imageRef.current
            const nextImage: ImageTileImage = currentImage
                ? { ...currentImage, src: url }
                : {
                      src: url,
                      alt: '',
                      title: '',
                      layout: 'contain',
                      position: DEFAULT_IMAGE_TILE_POSITION,
                  }
            setTextTileValues({
                body: imageTileToMarkdown(textCardConverter, nextImage),
            })
            setUploadComplete(true)
        },
        uploadFileOptions: {
            allowedMimeTypes: SUPPORTED_IMAGE_UPLOAD_TYPES,
            maxSizeBytes: MAX_IMAGE_UPLOAD_SIZE_BYTES,
        },
        onError: (detail) => {
            posthog.capture('dashboard image tile upload failed')
            if (detail === IMAGE_UPLOAD_ERROR_MESSAGES.NOT_AN_IMAGE) {
                lemonToast.error('Upload an image file.')
            } else if (detail === IMAGE_UPLOAD_ERROR_MESSAGES.UNSUPPORTED_TYPE) {
                lemonToast.error('Choose a PNG, JPG, GIF, WebP, or AVIF image.')
            } else if (detail === IMAGE_UPLOAD_ERROR_MESSAGES.TOO_LARGE) {
                lemonToast.error('Image must be 4 MB or smaller.')
            } else {
                lemonToast.error('We could not upload that image. Try again.')
            }
        },
    })
    const imageOperationInProgress = isTextTileSubmitting || uploading
    imageOperationInProgressRef.current = imageOperationInProgress

    useEffect(() => {
        if (!uploading && filesToUpload.length === 0) {
            uploadRequestedRef.current = false
        }
    }, [filesToUpload.length, uploading])

    const [initialBody] = useState(() =>
        imageTileId !== null ? dashboard.tiles?.find((tile) => tile.id === imageTileId)?.text?.body || '' : ''
    )
    const hasUnsavedInput = textTile.body !== initialBody

    const handleClose = (): void => {
        if (imageOperationInProgress) {
            return
        }

        resetTextTile()
        onClose()
    }

    const updateImageBody = (nextImage: ImageTileImage): void => {
        imageRef.current = nextImage
        setTextTileValues({ body: imageTileToMarkdown(textCardConverter, nextImage) })
    }

    const updateLayout = (layout: ImageTileImage['layout']): void => {
        const currentImage = imageRef.current
        if (!currentImage) {
            return
        }

        updateImageBody({
            ...currentImage,
            layout,
        })
    }

    const updatePosition = (position: ImageTilePosition): void => {
        const currentImage = imageRef.current
        if (!currentImage) {
            return
        }

        updateImageBody({ ...currentImage, position })
    }

    const handlePreviewPointerDown = (event: PointerEvent<HTMLElement>): void => {
        if (!image || imageOperationInProgress || event.button !== 0) {
            return
        }

        const rect = event.currentTarget.getBoundingClientRect()
        if (!rect.width || !rect.height) {
            return
        }

        previewDragRef.current = {
            pointerId: event.pointerId,
            startClientX: event.clientX,
            startClientY: event.clientY,
            startPosition: image.position,
            previewWidth: rect.width,
            previewHeight: rect.height,
        }
        previewPositionRef.current = null
        setPreviewPosition(null)
        event.currentTarget.setPointerCapture?.(event.pointerId)
        setIsDragging(true)
    }

    const handlePreviewPointerMove = (event: PointerEvent<HTMLElement>): void => {
        const drag = previewDragRef.current
        if (!drag || drag.pointerId !== event.pointerId || !image || imageOperationInProgress) {
            return
        }

        if (Math.hypot(event.clientX - drag.startClientX, event.clientY - drag.startClientY) <= 4) {
            return
        }

        const dragDirection = image.layout === 'cover' ? -1 : 1
        const nextPosition: ImageTilePosition = {
            x: Math.max(
                0,
                Math.min(
                    100,
                    drag.startPosition.x +
                        ((event.clientX - drag.startClientX) / drag.previewWidth) *
                            100 *
                            IMAGE_TILE_HORIZONTAL_DRAG_FACTOR *
                            dragDirection
                )
            ),
            y: Math.max(
                0,
                Math.min(
                    100,
                    drag.startPosition.y +
                        ((event.clientY - drag.startClientY) / drag.previewHeight) * 100 * dragDirection
                )
            ),
        }
        previewPositionRef.current = nextPosition
        setPreviewPosition(nextPosition)
    }

    const finishPreviewDrag = (event: PointerEvent<HTMLElement>, commitPosition: boolean): void => {
        const drag = previewDragRef.current
        if (!drag || drag.pointerId !== event.pointerId) {
            return
        }

        const position = previewPositionRef.current
        previewDragRef.current = null
        setIsDragging(false)
        if (commitPosition && !imageOperationInProgressRef.current && position) {
            updatePosition(position)
        } else {
            previewPositionRef.current = null
            setPreviewPosition(null)
        }
        if (event.currentTarget.hasPointerCapture?.(event.pointerId)) {
            event.currentTarget.releasePointerCapture?.(event.pointerId)
        }
    }

    const handlePreviewPointerEnd = (event: PointerEvent<HTMLElement>): void => {
        finishPreviewDrag(event, true)
    }

    const handlePreviewPointerCancel = (event: PointerEvent<HTMLElement>): void => {
        finishPreviewDrag(event, false)
    }

    const handlePreviewKeyDown = (event: KeyboardEvent<HTMLButtonElement>): void => {
        if (!image || imageOperationInProgress) {
            return
        }

        let nextPosition: ImageTilePosition | null = null
        if (event.key === 'ArrowLeft') {
            nextPosition = { ...image.position, x: image.position.x - IMAGE_TILE_POSITION_STEP }
        } else if (event.key === 'ArrowRight') {
            nextPosition = { ...image.position, x: image.position.x + IMAGE_TILE_POSITION_STEP }
        } else if (event.key === 'ArrowUp') {
            nextPosition = { ...image.position, y: image.position.y - IMAGE_TILE_POSITION_STEP }
        } else if (event.key === 'ArrowDown') {
            nextPosition = { ...image.position, y: image.position.y + IMAGE_TILE_POSITION_STEP }
        }

        if (nextPosition) {
            event.preventDefault()
            updatePosition(nextPosition)
        }
    }

    const bodyError = textTileValidationErrors.body as string | null
    let saveDisabledReason: string | null = bodyError
    if (uploading) {
        saveDisabledReason = 'Wait for image upload to finish'
    } else if (!image) {
        saveDisabledReason = 'Upload an image first'
    }
    let uploadDisabledReason: string | null = 'Image uploads are unavailable right now'
    if (isTextTileSubmitting) {
        uploadDisabledReason = 'Wait for image save to finish'
    } else if (uploading) {
        uploadDisabledReason = 'Wait for image upload to finish'
    } else if (objectStorageAvailable) {
        uploadDisabledReason = null
    }
    const handleImageSelection = (): void => {
        if (uploadDisabledReason) {
            return
        }

        fileInputRef.current?.click()
    }
    const handleFilesToUpload = (files: File[]): void => {
        if (files.length === 0 || imageOperationInProgressRef.current || uploadRequestedRef.current) {
            return
        }

        uploadRequestedRef.current = true
        setFilesToUpload(files)
    }
    const previewClassName = clsx(
        'flex aspect-video min-h-48 max-h-64 items-center justify-center overflow-hidden rounded border border-dashed border-primary bg-surface-secondary p-4 touch-none',
        image && (isDragging ? 'cursor-grabbing' : 'cursor-grab'),
        !image && (uploadDisabledReason ? 'cursor-not-allowed' : 'cursor-pointer')
    )

    return (
        <LemonModal
            isOpen={isOpen}
            onClose={handleClose}
            hasUnsavedInput={hasUnsavedInput || isTextTileSubmitting || uploading}
            title={isNewTile ? 'Add image' : 'Edit image'}
            description="Upload one image, choose how it appears in the tile, and reposition it."
            width={640}
            data-attr="image-tile-modal"
            footer={
                <>
                    <LemonButton
                        type="secondary"
                        onClick={handleClose}
                        disabledReason={imageOperationInProgress ? 'Wait for the image operation to finish' : null}
                    >
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        form="image-tile-form"
                        htmlType="submit"
                        loading={isTextTileSubmitting || uploading}
                        disabledReason={saveDisabledReason}
                        data-attr={isNewTile ? 'save-new-image-tile' : 'edit-image-tile'}
                    >
                        Save
                    </LemonButton>
                </>
            }
        >
            <Form
                logic={textCardModalLogic}
                props={modalLogicProps}
                formKey="textTile"
                id="image-tile-form"
                enableFormOnSubmit
            >
                <div className="flex flex-col gap-4">
                    {image ? (
                        <button
                            ref={setPreviewRef}
                            type="button"
                            className={previewClassName}
                            tabIndex={imageOperationInProgress ? -1 : 0}
                            aria-label="Drag to reposition the image"
                            aria-disabled={imageOperationInProgress || undefined}
                            onPointerDown={handlePreviewPointerDown}
                            onPointerMove={handlePreviewPointerMove}
                            onPointerUp={handlePreviewPointerEnd}
                            onPointerCancel={handlePreviewPointerCancel}
                            onLostPointerCapture={handlePreviewPointerCancel}
                            onKeyDown={handlePreviewKeyDown}
                            data-attr="image-tile-preview"
                        >
                            <img
                                src={previewImage?.src}
                                alt={previewImage?.alt || 'Dashboard image'}
                                draggable={false}
                                className={clsx(
                                    'pointer-events-none h-full w-full',
                                    previewImage?.layout === 'cover' ? 'object-cover' : 'object-contain'
                                )}
                                style={{
                                    objectPosition: imageTilePositionToCss(previewImage?.position ?? image.position),
                                }}
                                data-attr="image-tile-preview-image"
                            />
                        </button>
                    ) : (
                        <button
                            ref={setPreviewRef}
                            type="button"
                            className={clsx(previewClassName, 'text-secondary')}
                            onClick={handleImageSelection}
                            disabled={!!uploadDisabledReason}
                            data-attr="image-tile-preview"
                        >
                            <span className="flex flex-col items-center gap-2">
                                <IconImage className="text-3xl" />
                                <span>Drag and drop an image or click here to upload an image</span>
                            </span>
                        </button>
                    )}
                    {image && (
                        <LemonButton
                            type="secondary"
                            size="small"
                            className="self-start"
                            onClick={handleImageSelection}
                            disabledReason={uploadDisabledReason}
                            data-attr="replace-image-tile-image"
                        >
                            Replace image
                        </LemonButton>
                    )}
                    {!objectStorageAvailable && !imageOperationInProgress && (
                        <span className="text-sm text-danger" role="alert">
                            Image uploads are unavailable right now.
                        </span>
                    )}
                    {!image && (
                        <span className="text-xs text-secondary">
                            PNG, JPG, GIF, WebP, or AVIF. Maximum size: 4 MB.
                        </span>
                    )}
                    {image && (
                        <>
                            <div className="flex flex-col gap-1">
                                <LemonLabel htmlFor="image-tile-layout">Image display</LemonLabel>
                                <LemonSelect<ImageTileImage['layout']>
                                    id="image-tile-layout"
                                    value={image.layout}
                                    options={IMAGE_TILE_LAYOUT_OPTIONS}
                                    onChange={updateLayout}
                                    disabledReason={
                                        imageOperationInProgress
                                            ? 'Wait for the current image operation to finish'
                                            : null
                                    }
                                    fullWidth
                                    data-attr="image-tile-layout"
                                />
                            </div>
                            <Field name="transparent_background" label="">
                                {({ value, onChange }) => (
                                    <LemonSwitch
                                        checked={value}
                                        onChange={onChange}
                                        label="Transparent card background"
                                        disabledReason={
                                            imageOperationInProgress
                                                ? 'Wait for the current image operation to finish'
                                                : null
                                        }
                                        data-attr="image-tile-transparent-background"
                                    />
                                )}
                            </Field>
                            <div className="flex flex-col gap-1">
                                <LemonLabel htmlFor="image-tile-alt">Alt text</LemonLabel>
                                <LemonInput
                                    id="image-tile-alt"
                                    value={image.alt}
                                    onChange={(alt) => updateImageBody({ ...image, alt })}
                                    disabledReason={
                                        imageOperationInProgress
                                            ? 'Wait for the current image operation to finish'
                                            : null
                                    }
                                    fullWidth
                                    data-attr="image-tile-alt"
                                />
                                <span className="text-xs text-secondary">
                                    Used by screen readers. This text does not display on the image. Leave blank for a
                                    decorative image.
                                </span>
                            </div>
                        </>
                    )}
                    <div className="hidden">
                        <LemonFileInput
                            accept={SUPPORTED_IMAGE_UPLOAD_TYPES.join(',')}
                            multiple={false}
                            inputRef={fileInputRef}
                            alternativeDropTargetRef={previewRef as RefObject<HTMLElement>}
                            onChange={handleFilesToUpload}
                            loading={uploading}
                            value={filesToUpload}
                            showUploadedFiles={false}
                            disabledReason={uploadDisabledReason}
                        />
                    </div>
                    {uploadComplete && (
                        <span className="sr-only" role="status">
                            Image uploaded.
                        </span>
                    )}
                </div>
            </Form>
        </LemonModal>
    )
}
