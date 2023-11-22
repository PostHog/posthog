import './LemonFileInput.scss'

import clsx from 'clsx'
import { IconUploadFile } from 'lib/lemon-ui/icons'
import { LemonTag } from 'lib/lemon-ui/LemonTag/LemonTag'
import { Spinner } from 'lib/lemon-ui/Spinner/Spinner'
import { ChangeEvent, createRef, RefObject, useEffect, useState } from 'react'

export interface LemonFileInputProps extends Pick<HTMLInputElement, 'multiple' | 'accept'> {
    value?: File[]
    onChange?: (newValue: File[]) => void
    // are the files currently being uploaded?
    loading?: boolean
    /** if this is not provided then this component is the drop target
     * and is styled when a file is dragged over it
     * if this alternativeDropTargetRef is provided,
     * then it is also a drop target for files and
     * styling is applied to the alternativeDropTargetRef
     * **/
    alternativeDropTargetRef?: RefObject<HTMLElement>
}

export const LemonFileInput = ({
    value,
    onChange,
    multiple,
    loading,
    // e.g. '.json' or 'image/*'
    accept,
    alternativeDropTargetRef,
}: LemonFileInputProps): JSX.Element => {
    const [files, setFiles] = useState(value || value || ([] as File[]))

    // dragCounter and drag are used to track whether the user is dragging a file over the textarea
    // without drag counter the textarea highlight would flicker when the user drags a file over it
    let dragCounter = 0
    const [drag, setDrag] = useState(false)
    const dropRef = createRef<HTMLDivElement>()

    useEffect(() => {
        if (value && value !== files) {
            setFiles(value)
        }
    }, [value])

    const onInputChange = (e: ChangeEvent<HTMLInputElement>): void => {
        e.preventDefault()
        e.stopPropagation()

        const eventFiles = e.target.files
        const filesArr = Array.prototype.slice.call(eventFiles)
        const localFiles = multiple ? [...files, ...filesArr] : [filesArr[0]]
        setFiles(localFiles)
        onChange?.(localFiles)
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
    }, [value])

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
                className={clsx('flex flex-col gap-1', !alternativeDropTargetRef?.current && drag && 'FileDropTarget')}
            >
                <label className="text-muted inline-flex flex flow-row items-center gap-1 cursor-pointer">
                    <input
                        className={'hidden'}
                        type="file"
                        multiple={multiple}
                        accept={accept}
                        onChange={onInputChange}
                    />
                    <IconUploadFile className={'text-2xl'} /> Click or drag and drop to upload
                    {accept ? ` ${acceptToDisplayName(accept)}` : ''}
                </label>
                {files.length > 0 && (
                    <div className={'flex flex-row gap-2'}>
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
