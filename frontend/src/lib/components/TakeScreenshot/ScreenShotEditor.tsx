import { useActions, useValues } from 'kea'
import React, { useCallback, useEffect, useRef, useState } from 'react'

import { IconPencil, IconUndo } from '@posthog/icons'
import { LemonButton, LemonColorPicker, LemonInput, LemonModal, LemonSelect } from '@posthog/lemon-ui'

import { getSeriesColorPalette } from 'lib/colors'
import { Spinner } from 'lib/lemon-ui/Spinner/Spinner'
import { downloadFile } from 'lib/utils'

import { FilmCameraHog } from '../hedgehogs'
import {
    type DrawingItem,
    type HistoryItem,
    type Point,
    type TextItem,
    takeScreenshotLogic,
} from './takeScreenshotLogic'

export function ScreenShotEditor({ screenshotKey }: { screenshotKey: string }): JSX.Element {
    const {
        isOpen,
        imageFile,
        mode,
        color,
        isDrawing,
        originalImage,
        currentText,
        selectedTextIndex,
        dragStartOffset,
        textInputPosition,
        isLoading,
        lineWidth,
        fontSize,
    } = useValues(takeScreenshotLogic({ screenshotKey: screenshotKey }))
    const {
        setIsOpen,
        setMode,
        setColor,
        setIsDrawing,
        setOriginalImage,
        setCurrentText,
        setSelectedTextIndex,
        setDragStartOffset,
        setTextInputPosition,
        setImageFile,
        setLineWidth,
        setFontSize,
    } = useActions(takeScreenshotLogic({ screenshotKey: screenshotKey }))

    const canvasRef = useRef<HTMLCanvasElement | null>(null)
    const [drawings, setDrawings] = useState<DrawingItem[]>([])
    const [texts, setTexts] = useState<TextItem[]>([])
    const [currentPath, setCurrentPath] = useState<Point[]>([])
    const [historyStack, setHistoryStack] = useState<HistoryItem[]>([])

    const handleClose = useCallback(() => {
        setIsOpen(false)
        setOriginalImage(null)
        setDrawings([])
        setTexts([])
        setCurrentPath([])
        setCurrentText('')
        setTextInputPosition({ x: 0, y: 0, visible: false })
        setHistoryStack([])
        setSelectedTextIndex(null)
        setDragStartOffset(null)
        setMode('draw')
        setImageFile(null)
    }, [
        setIsOpen,
        setOriginalImage,
        setCurrentText,
        setTextInputPosition,
        setSelectedTextIndex,
        setDragStartOffset,
        setMode,
        setImageFile,
    ])

    const redrawCanvas = useCallback(() => {
        const canvas = canvasRef.current
        if (!canvas || !originalImage) {
            return
        }
        const ctx = canvas.getContext('2d')
        if (!ctx) {
            return
        }

        ctx.clearRect(0, 0, canvas.width, canvas.height)
        ctx.drawImage(originalImage, 0, 0, canvas.width, canvas.height)

        drawings.forEach((drawing) => {
            if (drawing.path.length < 2) {
                return
            }
            ctx.beginPath()
            ctx.moveTo(drawing.path[0].x, drawing.path[0].y)
            drawing.path.forEach((point) => ctx.lineTo(point.x, point.y))
            ctx.strokeStyle = drawing.color
            ctx.lineWidth = drawing.width
            ctx.lineCap = 'round'
            ctx.lineJoin = 'round'
            ctx.stroke()
        })

        if (isDrawing && mode === 'draw' && currentPath.length >= 2) {
            ctx.beginPath()
            ctx.moveTo(currentPath[0].x, currentPath[0].y)
            currentPath.forEach((point) => ctx.lineTo(point.x, point.y))
            ctx.strokeStyle = color
            ctx.lineWidth = lineWidth
            ctx.lineCap = 'round'
            ctx.lineJoin = 'round'
            ctx.stroke()
        }

        texts.forEach((textItem, index) => {
            ctx.fillStyle = textItem.color
            ctx.font = textItem.font
            ctx.fillText(textItem.content, textItem.x, textItem.y)

            // Draw selection box if text is selected
            if (index === selectedTextIndex) {
                const textWidth = ctx.measureText(textItem.content).width
                // Estimate height, or store it if calculated precisely elsewhere
                const textHeight = textItem.height || fontSize
                ctx.strokeStyle = '#007bff' // A distinct selection color
                ctx.lineWidth = 1
                ctx.strokeRect(textItem.x - 2, textItem.y - textHeight, textWidth + 4, textHeight + 4)
            }
        })
    }, [originalImage, drawings, texts, isDrawing, currentPath, color, mode, selectedTextIndex, lineWidth, fontSize])

    useEffect(() => {
        if (isOpen && imageFile && !originalImage) {
            const img = new Image()
            const objectUrl = URL.createObjectURL(imageFile)
            img.src = objectUrl
            img.onload = () => {
                setOriginalImage(img)
                setDrawings([])
                setTexts([])
                setHistoryStack([])
                setSelectedTextIndex(null)

                const canvas = canvasRef.current
                if (canvas) {
                    const maxDisplayWidth = window.innerWidth * 0.7
                    const maxDisplayHeight = window.innerHeight * 0.7

                    const { naturalWidth, naturalHeight } = img

                    const scaleX = maxDisplayWidth / naturalWidth
                    const scaleY = maxDisplayHeight / naturalHeight
                    const scale = Math.min(1, scaleX, scaleY)

                    canvas.width = naturalWidth * scale
                    canvas.height = naturalHeight * scale
                    const ctx = canvas.getContext('2d')
                    if (ctx) {
                        ctx.drawImage(img, 0, 0, canvas.width, canvas.height)
                    }
                }
            }
            img.onerror = () => {
                console.error('Error loading image.')
                URL.revokeObjectURL(objectUrl)
                handleClose()
            }
            return () => {
                URL.revokeObjectURL(objectUrl)
            }
        } else if (!isOpen) {
            setOriginalImage(null)
            setDrawings([])
            setTexts([])
            setHistoryStack([])
            setSelectedTextIndex(null)
        }
    }, [isOpen, imageFile, originalImage, handleClose, setOriginalImage, setSelectedTextIndex])

    useEffect(() => {
        if (isOpen && originalImage) {
            redrawCanvas()
        }
    }, [isOpen, originalImage, drawings, texts, currentPath, isDrawing, redrawCanvas, selectedTextIndex])

    const handleMouseDown = (event: React.MouseEvent<HTMLCanvasElement>): void => {
        if (!originalImage || !canvasRef.current) {
            return
        }
        const canvas = canvasRef.current
        const ctx = canvas.getContext('2d')
        if (!ctx) {
            return
        }

        const { offsetX, offsetY } = event.nativeEvent

        if (mode === 'draw') {
            setIsDrawing(true)
            setCurrentPath([{ x: offsetX, y: offsetY }])
            setSelectedTextIndex(null)
        } else if (mode === 'text' || mode === 'moveText') {
            let clickedTextIndex: number | null = null
            for (let i = texts.length - 1; i >= 0; i--) {
                const item = texts[i]
                const textMetrics = ctx.measureText(item.content)
                const textWidth = textMetrics.width
                const textHeight = item.height || fontSize

                if (
                    offsetX >= item.x &&
                    offsetX <= item.x + textWidth &&
                    offsetY >= item.y - textHeight &&
                    offsetY <= item.y
                ) {
                    clickedTextIndex = i
                    break
                }
            }

            if (clickedTextIndex !== null) {
                setMode('moveText')
                setSelectedTextIndex(clickedTextIndex)
                setIsDrawing(true)
                setDragStartOffset({
                    x: offsetX - texts[clickedTextIndex].x,
                    y: offsetY - texts[clickedTextIndex].y,
                })
                setTextInputPosition({ ...textInputPosition, visible: false })
            } else {
                if (mode === 'text') {
                    setSelectedTextIndex(null)
                    setTextInputPosition({ x: offsetX, y: offsetY, visible: true })
                } else {
                    setSelectedTextIndex(null)
                    setMode('text')
                }
            }
        }
    }

    const handleMouseMove = (event: React.MouseEvent<HTMLCanvasElement>): void => {
        if (!isDrawing || !originalImage) {
            return
        }
        const { offsetX, offsetY } = event.nativeEvent

        if (mode === 'draw') {
            setCurrentPath((prevPath) => [...prevPath, { x: offsetX, y: offsetY }])
        } else if (mode === 'moveText' && selectedTextIndex !== null && dragStartOffset) {
            const newX = offsetX - dragStartOffset.x
            const newY = offsetY - dragStartOffset.y
            setTexts((prevTexts) =>
                prevTexts.map((item, index) => (index === selectedTextIndex ? { ...item, x: newX, y: newY } : item))
            )
        }
    }

    const handleMouseUp = (): void => {
        if (!isDrawing) {
            return
        }

        if (mode === 'draw' && currentPath.length > 1) {
            setDrawings((prevDrawings) => [...prevDrawings, { path: currentPath, color: color, width: lineWidth }])
            setHistoryStack((prev) => [...prev, { type: 'draw' }])
            setCurrentPath([])
        }

        setIsDrawing(false)
        setDragStartOffset(null)
    }

    const handleCanvasClickForTextPlacement = (event: React.MouseEvent<HTMLCanvasElement>): void => {
        if (mode === 'text' && !textInputPosition.visible && selectedTextIndex === null) {
            const { offsetX, offsetY } = event.nativeEvent
            setTextInputPosition({ x: offsetX, y: offsetY, visible: true })
        }
    }

    const handleTextSubmit = (submittedText: string): void => {
        if (submittedText.trim() && textInputPosition.visible) {
            const canvas = canvasRef.current
            let textWidth = 0
            if (canvas) {
                const ctx = canvas.getContext('2d')
                if (ctx) {
                    ctx.font = `${fontSize}px Arial`
                    textWidth = ctx.measureText(submittedText).width
                }
            }

            setTexts((prevTexts) => [
                ...prevTexts,
                {
                    content: submittedText,
                    x: textInputPosition.x,
                    y: textInputPosition.y,
                    color: color,
                    font: `${fontSize}px Arial`,
                    width: textWidth,
                    height: fontSize,
                },
            ])
            setHistoryStack((prev) => [...prev, { type: 'text' }])
            setSelectedTextIndex(texts.length)
            setMode('moveText')
        }
        setCurrentText('')
        setTextInputPosition({ ...textInputPosition, visible: false })
    }

    const handleUndoLastChange = (): void => {
        if (historyStack.length === 0) {
            return
        }

        const lastAction = historyStack[historyStack.length - 1]

        if (lastAction.type === 'draw') {
            setDrawings((prevDrawings) => prevDrawings.slice(0, -1))
        } else if (lastAction.type === 'text') {
            setTexts((prevTexts) => prevTexts.slice(0, -1))
            if (selectedTextIndex === texts.length - 1) {
                setSelectedTextIndex(null)
            }
        }

        setHistoryStack((prev) => prev.slice(0, -1))
    }

    const handleSave = async (): Promise<void> => {
        if (!canvasRef.current || !originalImage) {
            return
        }
        setSelectedTextIndex(null)

        await new Promise((resolve) => setTimeout(resolve, 50))

        redrawCanvas()

        const canvas = canvasRef.current
        if (!canvas) {
            return
        }
        const dataURL = canvas.toDataURL('image/png')

        async function dataURLtoFile(dataurl: string, filename: string): Promise<File> {
            const res = await fetch(dataurl)
            const blob = await res.blob()
            return new File([blob], filename, { type: blob.type })
        }

        // Assume imageFile is a File object if it exists, to satisfy TypeScript for now.
        // Ideally, this type comes from the Kea logic.
        const currentImageFile = imageFile

        const finalFilename = currentImageFile ? `edited-${currentImageFile.name}` : 'edited-screenshot.png'
        const editedFile = await dataURLtoFile(dataURL, finalFilename)
        downloadFile(editedFile)
    }

    if (isLoading) {
        return (
            <>
                <LemonModal isOpen={isOpen} onClose={handleClose} width="auto" maxWidth="100%">
                    <div className="flex flex-col items-center justify-center py-10">
                        <FilmCameraHog className="h-32 w-32" />
                        <div className="mt-2">
                            <Spinner className="mr-4" />
                            Taking a screenshot...
                        </div>
                    </div>
                </LemonModal>
            </>
        )
    }

    return (
        <>
            <LemonModal
                isOpen={isOpen}
                onClose={handleClose}
                title="Edit Screenshot"
                description="Draw or add text to your screenshot."
                width="80%"
                maxWidth="100%"
                footer={
                    <div className="flex justify-between items-center w-full">
                        <div className="flex gap-2 items-center">
                            <LemonColorPicker
                                selectedColor={color}
                                onSelectColor={(newColor) => {
                                    setColor(newColor)
                                }}
                                colors={getSeriesColorPalette().slice(0, 20)}
                            />
                            <LemonSelect
                                value={lineWidth}
                                onChange={setLineWidth}
                                options={Array.from({ length: 10 }, (_, i) => {
                                    const value = 1 + i * 2
                                    return {
                                        label: (
                                            <div
                                                className="w-12 bg-gray-700 rounded-full"
                                                // eslint-disable-next-line react/forbid-dom-props
                                                style={{ height: `${value}px` }}
                                            />
                                        ),
                                        value,
                                    }
                                })}
                            />
                            <LemonButton
                                type={mode === 'draw' ? 'primary' : 'secondary'}
                                onClick={() => {
                                    setMode('draw')
                                    setSelectedTextIndex(null)
                                    setTextInputPosition({ ...textInputPosition, visible: false })
                                }}
                                icon={<IconPencil />}
                                tooltip="Draw"
                            />
                            <LemonSelect
                                value={fontSize}
                                onChange={setFontSize}
                                options={Array.from({ length: 20 }, (_, i) => {
                                    const value = 10 + i * 2
                                    return { label: value.toString(), value }
                                })}
                            />
                            <LemonButton
                                type={mode === 'text' || mode === 'moveText' ? 'primary' : 'secondary'}
                                onClick={() => {
                                    setMode('text')
                                }}
                                tooltip="Add or Move Text"
                            >
                                Text
                            </LemonButton>
                            <LemonButton
                                onClick={handleUndoLastChange}
                                disabledReason={historyStack.length === 0 ? 'No actions to undo' : undefined}
                                icon={<IconUndo />}
                                tooltip="Undo"
                            />
                        </div>
                        <div className="flex gap-2 items-center">
                            <LemonButton type="secondary" onClick={handleClose}>
                                Cancel
                            </LemonButton>
                            <LemonButton
                                type="primary"
                                onClick={() => {
                                    void handleSave()
                                }}
                            >
                                Download
                            </LemonButton>
                        </div>
                    </div>
                }
            >
                <div className="flex flex-col gap-4 max-h-[80vh]">
                    <div
                        className={`flex-grow flex justify-center items-center overflow-hidden ${
                            mode === 'moveText' && selectedTextIndex !== null
                                ? 'cursor-move'
                                : mode === 'draw'
                                  ? 'cursor-crosshair'
                                  : 'cursor-text'
                        }`}
                    >
                        <canvas
                            ref={canvasRef}
                            onMouseDown={handleMouseDown}
                            onMouseMove={handleMouseMove}
                            onMouseUp={handleMouseUp}
                            onMouseLeave={handleMouseUp}
                            onClick={handleCanvasClickForTextPlacement}
                            className={`border border-gray-300 ${
                                originalImage ? 'block' : 'hidden'
                            } max-w-full max-h-full object-contain`}
                        />
                        {!originalImage && imageFile && <p>Loading image...</p>}
                        {!originalImage && !imageFile && <p>No image selected.</p>}

                        {mode === 'text' && textInputPosition.visible && selectedTextIndex === null && (
                            <div
                                className="absolute bg-white border rounded p-1 z-10"
                                // eslint-disable-next-line react/forbid-dom-props
                                style={{ top: textInputPosition.y, left: textInputPosition.x }}
                            >
                                <LemonInput
                                    value={currentText}
                                    onChange={setCurrentText}
                                    onKeyDown={(e) => {
                                        if (e.key === 'Enter') {
                                            e.preventDefault()
                                            handleTextSubmit(currentText)
                                        } else if (e.key === 'Escape') {
                                            setTextInputPosition({ ...textInputPosition, visible: false })
                                            setCurrentText('')
                                        }
                                    }}
                                    autoFocus
                                    placeholder="Type and press Enter"
                                />
                                <div className="flex gap-2 items-center mt-2">
                                    <LemonButton
                                        size="small"
                                        type="primary"
                                        onClick={() => handleTextSubmit(currentText)}
                                        className="ml-1"
                                    >
                                        Add
                                    </LemonButton>
                                    <LemonButton
                                        size="small"
                                        type="secondary"
                                        onClick={() => {
                                            setTextInputPosition({ ...textInputPosition, visible: false })
                                            setCurrentText('')
                                        }}
                                        className="ml-1"
                                    >
                                        Cancel
                                    </LemonButton>
                                </div>
                            </div>
                        )}
                    </div>
                </div>
            </LemonModal>
        </>
    )
}
