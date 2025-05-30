import { actions, kea, listeners, path, reducers } from 'kea'

import type { takeScreenshotLogicType } from './takeScreenshotLogicType'

export const LINE_WIDTH = 3
export const TEXT_FONT = '16px Arial'
export const APPROX_TEXT_HEIGHT = 16

// Define interfaces for better type safety
export interface Point {
    x: number
    y: number
}

export interface DrawingItem {
    path: Point[]
    color: string
    width: number
}

export interface TextItem {
    content: string
    x: number
    y: number
    color: string
    font: string
    width?: number // For bounding box, useful for moving
    height?: number // For bounding box, useful for moving
}

export interface HistoryItem {
    type: 'draw' | 'text'
}

export const takeScreenshotLogic = kea<takeScreenshotLogicType>([
    path(['lib', 'components', 'TakeScreenshot', 'takeScreenshotLogic']),
    actions({
        setIsOpen: (isOpen: boolean) => ({ isOpen }),
        setImageFile: (imageFile: File | null) => ({ imageFile }),
        setMode: (mode: 'draw' | 'text' | 'moveText') => ({ mode }),
        setDrawings: (drawings: DrawingItem[]) => ({ drawings }),
        setTexts: (texts: TextItem[]) => ({ texts }),
        setHistoryStack: (historyStack: HistoryItem[]) => ({ historyStack }),
        setSelectedTextIndex: (selectedTextIndex: number | null) => ({ selectedTextIndex }),
        setDragStartOffset: (dragStartOffset: Point | null) => ({ dragStartOffset }),
        setColor: (color: string) => ({ color }),
        setOriginalImage: (originalImage: HTMLImageElement | null) => ({ originalImage }),
        setIsDrawing: (isDrawing: boolean) => ({ isDrawing }),
        setCurrentPath: (currentPath: Point[]) => ({ currentPath }),
        setCurrentText: (currentText: string) => ({ currentText }),
        setTextInputPosition: (textInputPosition: { x: number; y: number; visible: boolean }) => ({
            textInputPosition,
        }),
    }),
    reducers({
        isOpen: [
            false,
            {
                setIsOpen: (_, { isOpen }) => isOpen,
            },
        ],
        imageFile: [
            null,
            {
                setImageFile: (_, { imageFile }) => imageFile,
            },
        ],
        mode: [
            'draw',
            {
                setMode: (_, { mode }) => mode,
            },
        ],
        drawings: [
            [],
            {
                setDrawings: (_, { drawings }) => drawings,
            },
        ],
        texts: [
            [],
            {
                setTexts: (_, { texts }) => texts,
            },
        ],
        historyStack: [
            [],
            {
                setHistoryStack: (_, { historyStack }) => historyStack,
            },
        ],
        selectedTextIndex: [
            null,
            {
                setSelectedTextIndex: (_, { selectedTextIndex }) => selectedTextIndex,
            },
        ],
        dragStartOffset: [
            null,
            {
                setDragStartOffset: (_, { dragStartOffset }) => dragStartOffset,
            },
        ],
        color: [
            '#FF0000',
            {
                setColor: (_, { color }) => color,
            },
        ],
        originalImage: [
            null,
            {
                setOriginalImage: (_, { originalImage }) => originalImage,
            },
        ],
        isDrawing: [
            false,
            {
                setIsDrawing: (_, { isDrawing }) => isDrawing,
            },
        ],
        currentPath: [
            [],
            {
                setCurrentPath: (_, { currentPath }) => currentPath,
            },
        ],
        currentText: [
            '',
            {
                setCurrentText: (_, { currentText }) => currentText,
            },
        ],
        textInputPosition: [
            { x: 0, y: 0, visible: false },
            {
                setTextInputPosition: (_, { textInputPosition }) => textInputPosition,
            },
        ],
    }),
    listeners(() => ({})),
])
