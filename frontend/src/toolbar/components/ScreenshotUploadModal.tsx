import { useEffect, useState } from 'react'

import api from 'lib/api'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { lemonToast } from 'lib/lemon-ui/LemonToast'

import { createObjectMediaPreview, uploadScreenshotImage } from '~/toolbar/utils/screenshotUpload'
import { EventDefinition } from '~/types'

export interface ScreenshotUploadModalProps {
    isOpen: boolean
    setIsOpen: (open: boolean) => void
    screenshot: Blob | null
    onSuccess?: () => void
}

export const ScreenshotUploadModal = ({
    isOpen,
    setIsOpen,
    screenshot,
    onSuccess,
}: ScreenshotUploadModalProps): JSX.Element => {
    const [eventName, setEventName] = useState('')
    const [isUploading, setIsUploading] = useState(false)
    const [previewUrl, setPreviewUrl] = useState<string | null>(null)
    const [eventDefinitions, setEventDefinitions] = useState<EventDefinition[]>([])
    const [isLoadingEvents, setIsLoadingEvents] = useState(false)
    const [showSuggestions, setShowSuggestions] = useState(false)

    useEffect(() => {
        if (isOpen) {
            setIsLoadingEvents(true)
            api.get('api/projects/@current/event_definitions/?limit=100')
                .then((response) => {
                    if (response.results) {
                        setEventDefinitions(response.results)
                    }
                })
                .catch((error) => {
                    console.error('Failed to load event definitions:', error)
                })
                .finally(() => {
                    setIsLoadingEvents(false)
                })
        }
    }, [isOpen])

    useEffect(() => {
        if (screenshot && isOpen && !previewUrl) {
            const url = URL.createObjectURL(screenshot)
            setPreviewUrl(url)
        }
    }, [screenshot, isOpen, previewUrl])

    const handleClose = (): void => {
        if (previewUrl) {
            URL.revokeObjectURL(previewUrl)
            setPreviewUrl(null)
        }
        setEventName('')
        setIsUploading(false)
        setIsOpen(false)
    }

    const filteredEventDefinitions = eventDefinitions
        .filter((ed) => ed.name.toLowerCase().includes(eventName.toLowerCase()))
        .slice(0, 10)

    const handleSubmit = async (): Promise<void> => {
        if (!screenshot || !eventName.trim()) {
            lemonToast.error('Please enter an event name')
            return
        }

        setIsUploading(true)

        try {
            const timestamp = new Date().toISOString().replace(/[:.]/g, '-')
            const filename = `screenshot-${timestamp}.png`

            const uploadResult = await uploadScreenshotImage(screenshot, filename)

            const exactMatch = eventDefinitions.find((ed) => ed.name === eventName)
            if (!exactMatch) {
                lemonToast.error(`Event "${eventName}" not found. Please select an existing event.`)
                setIsUploading(false)
                return
            }

            await createObjectMediaPreview(uploadResult.id, exactMatch.id)

            lemonToast.success('Screenshot uploaded successfully')
            handleClose()
            onSuccess?.()
        } catch (error) {
            lemonToast.error(`Failed to upload screenshot: ${error}`)
            setIsUploading(false)
        }
    }

    const handleEventNameChange = (value: string): void => {
        setEventName(value)
        setShowSuggestions(value.length > 0)
    }

    const handleSelectEvent = (name: string): void => {
        setEventName(name)
        setShowSuggestions(false)
    }

    return (
        <LemonModal
            forceAbovePopovers={true}
            title="Upload event screenshot"
            description="Add a screenshot to an event definition"
            footer={
                <>
                    <LemonButton type="secondary" onClick={handleClose} disabled={isUploading}>
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        onClick={handleSubmit}
                        loading={isUploading}
                        disabled={!eventName.trim()}
                    >
                        Upload
                    </LemonButton>
                </>
            }
            onClose={handleClose}
            isOpen={isOpen}
        >
            <div className="flex flex-col gap-4">
                <div className="relative">
                    <label className="text-sm font-semibold mb-1 block">Event name</label>
                    <LemonInput
                        placeholder={isLoadingEvents ? 'Loading events...' : 'Type to search events...'}
                        value={eventName}
                        onChange={handleEventNameChange}
                        onFocus={() => eventName.length > 0 && setShowSuggestions(true)}
                        onBlur={() => setTimeout(() => setShowSuggestions(false), 200)}
                        disabled={isUploading || isLoadingEvents}
                        autoFocus
                    />
                    {showSuggestions && filteredEventDefinitions.length > 0 && (
                        <div className="absolute z-10 w-full mt-1 bg-bg-light border border-border rounded shadow-md max-h-60 overflow-y-auto">
                            {filteredEventDefinitions.map((ed) => (
                                <div
                                    key={ed.id}
                                    className="px-3 py-2 hover:bg-bg-3000 cursor-pointer"
                                    onClick={() => handleSelectEvent(ed.name)}
                                    onMouseDown={(e) => e.preventDefault()}
                                >
                                    {ed.name}
                                </div>
                            ))}
                        </div>
                    )}
                </div>

                {previewUrl && (
                    <div>
                        <label className="text-sm font-semibold mb-1 block">Preview</label>
                        <div className="border rounded overflow-hidden">
                            <img
                                src={previewUrl}
                                alt="Screenshot preview"
                                className="w-full h-auto"
                                style={{ maxHeight: '400px', objectFit: 'contain' }}
                            />
                        </div>
                    </div>
                )}
            </div>
        </LemonModal>
    )
}
