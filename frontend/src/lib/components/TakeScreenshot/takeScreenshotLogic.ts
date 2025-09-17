import { actions, kea, key, listeners, path, props, reducers } from 'kea'
import posthog from 'posthog-js'

import { lemonToast } from '@posthog/lemon-ui'

import type { takeScreenshotLogicType } from './takeScreenshotLogicType'

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

export interface TakeScreenshotLogicProps {
    screenshotKey?: string
}

export const takeScreenshotLogic = kea<takeScreenshotLogicType>([
    path((key) => ['lib', 'components', 'TakeScreenshot', 'takeScreenshotLogic', key]),
    props({} as TakeScreenshotLogicProps),
    key((props: TakeScreenshotLogicProps) => props.screenshotKey || 'default-key'),
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
        setIsLoading: (isLoading: boolean) => ({ isLoading }),
        setBlob: (blob: Blob) => ({ blob }),
        setLineWidth: (lineWidth: number) => ({ lineWidth }),
        setFontSize: (fontSize: number) => ({ fontSize }),
    }),
    reducers({
        isOpen: [
            false,
            {
                setIsOpen: (_, { isOpen }) => isOpen,
            },
        ],
        isLoading: [
            false,
            {
                setIsLoading: (_, { isLoading }) => isLoading,
            },
        ],
        imageFile: [
            null as File | null,
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
            null as number | null,
            {
                setSelectedTextIndex: (_, { selectedTextIndex }) => selectedTextIndex,
            },
        ],
        dragStartOffset: [
            null as Point | null,
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
            null as HTMLImageElement | null,
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
            { x: 0, y: 0, visible: false } as { x: number; y: number; visible: boolean },
            {
                setTextInputPosition: (_, { textInputPosition }) => textInputPosition,
            },
        ],
        lineWidth: [
            3,
            {
                setLineWidth: (_, { lineWidth }) => lineWidth,
            },
        ],
        fontSize: [
            16,
            {
                setFontSize: (_, { fontSize }) => fontSize,
            },
        ],
    }),
    listeners(({ actions, props }) => ({
        setBlob: async ({ blob }) => {
            if (!blob) {
                lemonToast.error('Cannot take screenshot. Please try again.')
                posthog.capture('screenshot_failed', {
                    screenshot_key: props.screenshotKey,
                })
                return
            }
            actions.setIsLoading(true)
            actions.setIsOpen(true)

            const image = new File([blob], 'screenshot.png', { type: 'image/png' })
            actions.setImageFile(image)
            actions.setIsLoading(false)

            posthog.capture('screenshot_taken', {
                screenshot_key: props.screenshotKey,
            })
        },
    })),
])
