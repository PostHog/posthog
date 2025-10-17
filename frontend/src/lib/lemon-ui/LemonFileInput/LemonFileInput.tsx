import './LemonFileInput.scss'

import clsx from 'clsx'
import { ChangeEvent, RefObject, createRef, useEffect, useState } from 'react'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonTag } from 'lib/lemon-ui/LemonTag/LemonTag'
import { Spinner } from 'lib/lemon-ui/Spinner/Spinner'
import { IconUploadFile } from 'lib/lemon-ui/icons'

export interface LemonFileInputProps extends Pick<HTMLInputElement, 'multiple' | 'accept'> {
    value?: File[]
    onChange?: (newValue: File[]) => void
    /**
     * are the files currently being uploaded?
     */
    loading?: boolean
    /** Like plain `disabled`, except we enforce a reason to be shown in the tooltip. */
    disabledReason?: string | null
    /** if this is not provided then this component is the drop target
     * and is styled when a file is dragged over it
     * if this alternativeDropTargetRef is provided,
     * then it is also a drop target for files and
     * styling is applied to the alternativeDropTargetRef
     * **/
    alternativeDropTargetRef?: RefObject<HTMLElement>
    /**
     * the text to display to the user, a sensible default is used if not provided
     */
    callToAction?: string | JSX.Element
    /**
     * whether to show the uploaded files beneath the upload input
     */
    showUploadedFiles?: boolean
}

export const LemonFileInput = ({
    value,
    onChange,
    multiple,
    loading,
    disabledReason,
    // e.g. '.json' or 'image/*'
    accept,
    alternativeDropTargetRef,
    callToAction,
    showUploadedFiles = true,
}: LemonFileInputProps): JSX.Element => {
    const [files, setFiles] = useState(value || value || ([] as File[]))

    // dragCounter and drag are used to track whether the user is dragging a file over the textarea
    // without drag counter the textarea highlight would flicker when the user drags a file over it
    let dragCounter = 0
    const [drag, setDrag] = useState(false)
    const dropRef = createRef<HTMLDivElement>()
    const fileInputRef = createRef<HTMLInputElement>()

    useEffect(() => {
        if (value && value !== files) {
            setFiles(value)
        }
    }, [value]) // oxlint-disable-line react-hooks/exhaustive-deps

    const handleCallToActionClick = (): void => {
        if (!disabledReason && fileInputRef.current) {
            fileInputRef.current.click()
        }
    }

    const onInputChange = (e: ChangeEvent<HTMLInputElement>): void => {
        e.preventDefault()
        e.stopPropagation()

        const eventFiles = e.target.files
        const filesArr = Array.prototype.slice.call(eventFiles)
        if (filesArr.length > 0) {
            const localFiles = multiple ? [...files, ...filesArr] : filesArr.slice(0, 1)
            setFiles(localFiles)
            onChange?.(localFiles)
        }
    }

    const handleDrag = (e: DragEvent): void => {
        e.preventDefault()
        e.stopPropagation()
    }

    const handleDragIn = (e: DragEvent): void => {
        e.preventDefault()
        e.stopPropagation()
        dragCounter++
        if (e.dataTransfer?.items && e.dataTransfer.items.length > 0) {
            setDrag(true)
        }
    }

    const handleDragOut = (e: DragEvent): void => {
        e.preventDefault()
        e.stopPropagation()
        dragCounter--
        if (dragCounter === 0) {
            setDrag(false)
        }
    }

    const handleDrop = (e: DragEvent): void => {
        e.preventDefault()
        e.stopPropagation()
        setDrag(false)
        if (e.dataTransfer?.files && e.dataTransfer.files.length > 0) {
            const filesArr = Array.prototype.slice.call(e.dataTransfer?.files)
            const localFiles = multiple ? [...files, ...filesArr] : [filesArr[0]]
            setFiles(localFiles)
            onChange?.(localFiles)
            dragCounter = 0
        }
    }

    useEffect(() => {
        const div = (alternativeDropTargetRef || dropRef)?.current
        if (!div) {
            return
        }
        div.addEventListener('dragenter', handleDragIn)
        div.addEventListener('dragleave', handleDragOut)
        div.addEventListener('dragover', handleDrag)
        div.addEventListener('drop', handleDrop)
        return () => {
            div?.removeEventListener('dragenter', handleDragIn)
            div?.removeEventListener('dragleave', handleDragOut)
            div?.removeEventListener('dragover', handleDrag)
            div?.removeEventListener('drop', handleDrop)
        }
    }, [value, handleDrop, handleDragOut, alternativeDropTargetRef, dropRef, handleDragIn])

    useEffect(() => {
        const extraDragTarget = alternativeDropTargetRef?.current
        if (!extraDragTarget) {
            return
        }
        extraDragTarget.classList.add('FileDropTarget')
        if (drag) {
            extraDragTarget.classList.add('FileDropTarget--active')
        } else {
            extraDragTarget.classList.remove('FileDropTarget--active')
        }
    }, [drag, alternativeDropTargetRef])

    return (
        <>
            <div
                ref={dropRef}
                className={clsx(
                    'FileDropTarget flex flex-col gap-1',
                    !alternativeDropTargetRef?.current && drag && 'FileDropTarget--active'
                )}
                aria-disabled={!!disabledReason}
            >
                <input
                    ref={fileInputRef}
                    className="hidden"
                    type="file"
                    multiple={multiple}
                    accept={accept}
                    onChange={onInputChange}
                    disabled={!!disabledReason}
                />
                <div
                    className={clsx(
                        'text-secondary inline-flex flow-row items-center gap-1',
                        disabledReason ? 'cursor-not-allowed' : 'cursor-pointer'
                    )}
                    onClick={handleCallToActionClick}
                >
                    {callToAction || (
                        <LemonButton icon={<IconUploadFile />} type="tertiary" disabledReason={disabledReason}>
                            Click or drag and drop to upload
                            {accept ? ` ${acceptToDisplayName(accept)}` : ''}
                        </LemonButton>
                    )}
                </div>
                {files.length > 0 && showUploadedFiles && (
                    <div className="flex flex-row gap-2">
                        {files.map((x, i) => (
                            <LemonTag key={i} icon={loading ? <Spinner /> : undefined}>
                                {x.name}
                            </LemonTag>
                        ))}
                    </div>
                )}
            </div>
        </>
    )
}

function acceptToDisplayName(accept: string): string {
    const match = accept.match(/(\w+)\/\*/)
    if (match) {
        return `${match[1]}s`
    }
    if (accept.startsWith('.')) {
        return `${accept.slice(1).toUpperCase()} files`
    }
    return `files`
}
