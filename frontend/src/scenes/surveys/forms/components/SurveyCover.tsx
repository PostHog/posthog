import { useActions, useValues } from 'kea'
import { useCallback, useRef, useState } from 'react'

import { IconImage, IconPalette, IconPencil, IconTrash } from '@posthog/icons'
import { LemonButton, LemonMenu, Popover } from '@posthog/lemon-ui'

import { Spinner } from 'lib/lemon-ui/Spinner'

import { ColorInput } from '../../wizard/ColorInput'
import { surveyFormBuilderLogic } from '../surveyFormBuilderLogic'

export function SurveyCover(): JSX.Element {
    const { surveyForm, coverImageUploading } = useValues(surveyFormBuilderLogic)
    const { uploadImage, removeCover, removeCoverImage, setSurveyFormValues } = useActions(surveyFormBuilderLogic)

    const fileInputRef = useRef<HTMLInputElement>(null)
    const coverRef = useRef<HTMLDivElement>(null)

    const [repositioning, setRepositioning] = useState(false)
    const [tempPosition, setTempPosition] = useState({ x: 50, y: 50 })
    const [colorPickerOpen, setColorPickerOpen] = useState(false)
    const draggingRef = useRef(false)

    const hasImage = !!surveyForm.coverImageMediaId || !!surveyForm.coverImageUrl
    const imageSrc = surveyForm.coverImageMediaId
        ? `/uploaded_media/${surveyForm.coverImageMediaId}`
        : surveyForm.coverImageUrl

    const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>): void => {
        const file = e.target.files?.[0]
        if (file) {
            uploadImage(file, 'cover')
        }
        e.target.value = ''
    }

    const startReposition = (): void => {
        setTempPosition({ ...surveyForm.coverImagePosition })
        setRepositioning(true)
    }

    const saveReposition = (): void => {
        setSurveyFormValues({ coverImagePosition: tempPosition })
        setRepositioning(false)
    }

    const cancelReposition = (): void => {
        setRepositioning(false)
    }

    const handleMouseDown = useCallback(
        (e: React.MouseEvent): void => {
            if (!repositioning) {
                return
            }
            e.preventDefault()
            draggingRef.current = true

            const startX = e.clientX
            const startY = e.clientY
            const startPos = { ...tempPosition }
            const rect = coverRef.current?.getBoundingClientRect()
            if (!rect) {
                return
            }

            const onMouseMove = (moveEvent: MouseEvent): void => {
                const dx = moveEvent.clientX - startX
                const dy = moveEvent.clientY - startY
                const pctX = startPos.x - (dx / rect.width) * 100
                const pctY = startPos.y - (dy / rect.height) * 100
                setTempPosition({
                    x: Math.max(0, Math.min(100, pctX)),
                    y: Math.max(0, Math.min(100, pctY)),
                })
            }

            const onMouseUp = (): void => {
                draggingRef.current = false
                document.removeEventListener('mousemove', onMouseMove)
                document.removeEventListener('mouseup', onMouseUp)
            }

            document.addEventListener('mousemove', onMouseMove)
            document.addEventListener('mouseup', onMouseUp)
        },
        [repositioning, tempPosition]
    )

    const activePosition = repositioning ? tempPosition : surveyForm.coverImagePosition

    const menuItems = [
        {
            items: [
                {
                    label: 'Upload image',
                    icon: <IconImage />,
                    onClick: () => fileInputRef.current?.click(),
                },
                {
                    label: 'Pick color',
                    icon: <IconPalette />,
                    onClick: () => {
                        if (hasImage) {
                            removeCoverImage()
                        }
                        setColorPickerOpen(true)
                    },
                },
                {
                    label: 'Remove',
                    icon: <IconTrash />,
                    status: 'danger' as const,
                    onClick: removeCover,
                },
            ],
        },
    ]

    return (
        <Popover
            visible={colorPickerOpen}
            onClickOutside={() => setColorPickerOpen(false)}
            overlay={
                <div className="p-3 w-64">
                    <ColorInput
                        value={surveyForm.coverColor}
                        onChange={(color) => setSurveyFormValues({ coverColor: color })}
                    />
                </div>
            }
            placement="bottom"
        >
            <div
                ref={coverRef}
                className="relative h-[200px] overflow-hidden group"
                style={!hasImage ? { backgroundColor: surveyForm.coverColor } : undefined}
                onMouseDown={hasImage ? handleMouseDown : undefined}
            >
                {hasImage && imageSrc && (
                    <img
                        src={imageSrc}
                        alt="Cover"
                        className="w-full h-full object-cover select-none"
                        style={{ objectPosition: `${activePosition.x}% ${activePosition.y}%` }}
                        draggable={false}
                    />
                )}
                {coverImageUploading && (
                    <div className="absolute inset-0 flex items-center justify-center bg-overlay">
                        <Spinner className="text-2xl text-white" />
                    </div>
                )}
                {repositioning ? (
                    <div className="absolute inset-0" style={{ cursor: draggingRef.current ? 'grabbing' : 'grab' }}>
                        <div className="absolute top-3 right-3 flex gap-2">
                            <LemonButton type="secondary" size="small" className="bg-bg-light" onClick={saveReposition}>
                                Save position
                            </LemonButton>
                            <LemonButton
                                type="tertiary"
                                size="small"
                                className="bg-bg-light"
                                onClick={cancelReposition}
                            >
                                Cancel
                            </LemonButton>
                        </div>
                    </div>
                ) : (
                    !coverImageUploading && (
                        <div className="absolute inset-0 flex items-center justify-center gap-2 bg-overlay opacity-0 group-hover:opacity-100 transition-opacity">
                            <LemonMenu items={menuItems} placement="bottom">
                                <LemonButton
                                    type="secondary"
                                    size="small"
                                    icon={<IconPencil />}
                                    className="bg-bg-light"
                                >
                                    Change
                                </LemonButton>
                            </LemonMenu>
                            {hasImage && (
                                <LemonButton
                                    type="secondary"
                                    size="small"
                                    className="bg-bg-light"
                                    onClick={startReposition}
                                >
                                    Reposition
                                </LemonButton>
                            )}
                        </div>
                    )
                )}
                <input ref={fileInputRef} type="file" accept="image/*" className="hidden" onChange={handleFileChange} />
            </div>
        </Popover>
    )
}
