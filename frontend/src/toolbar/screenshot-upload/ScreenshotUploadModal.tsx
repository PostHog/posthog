import { useActions, useValues } from 'kea'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { LemonModal } from 'lib/lemon-ui/LemonModal'

import { screenshotUploadLogic } from '~/toolbar/screenshot-upload/screenshotUploadLogic'

export const ScreenshotUploadModal = (): JSX.Element => {
    const {
        isModalOpen,
        eventName,
        showSuggestions,
        eventDefinitions,
        eventDefinitionsLoading,
        uploadResultLoading,
        previewUrl,
        selectedDefinition,
    } = useValues(screenshotUploadLogic)
    const { setEventName, selectEvent, setShowSuggestions, submitUpload, closeModal } =
        useActions(screenshotUploadLogic)

    return (
        <LemonModal
            forceAbovePopovers={true}
            title="Upload event screenshot"
            description="Add a screenshot to an event definition"
            footer={
                <>
                    <LemonButton
                        type="secondary"
                        onClick={closeModal}
                        disabledReason={uploadResultLoading ? 'Upload in progress' : null}
                    >
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        onClick={submitUpload}
                        loading={uploadResultLoading}
                        disabledReason={!selectedDefinition ? 'Select an event first' : null}
                    >
                        Upload
                    </LemonButton>
                </>
            }
            onClose={closeModal}
            isOpen={isModalOpen}
        >
            <div className="flex flex-col gap-4">
                <div className="relative">
                    <label className="text-sm font-semibold mb-1 block">Event name</label>
                    <LemonInput
                        placeholder="Type to search events..."
                        value={eventName}
                        onChange={setEventName}
                        onFocus={() => eventName.length > 0 && setShowSuggestions(true)}
                        onBlur={() => setTimeout(() => setShowSuggestions(false), 200)}
                        disabledReason={uploadResultLoading ? 'Upload in progress' : null}
                        autoFocus
                    />
                    {showSuggestions && eventName.trim() && (
                        <div className="absolute z-10 w-full mt-1 bg-bg-light border border-border rounded shadow-md max-h-60 overflow-y-auto">
                            {eventDefinitionsLoading ? (
                                <div className="px-3 py-2 text-muted">Loading events...</div>
                            ) : eventDefinitions.length > 0 ? (
                                eventDefinitions.map((ed) => (
                                    <div
                                        key={ed.id}
                                        className="px-3 py-2 hover:bg-bg-3000 cursor-pointer"
                                        onClick={() => selectEvent(ed)}
                                        onMouseDown={(e) => e.preventDefault()}
                                    >
                                        {ed.name}
                                    </div>
                                ))
                            ) : (
                                <div className="px-3 py-2 text-muted">No matching events found</div>
                            )}
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
