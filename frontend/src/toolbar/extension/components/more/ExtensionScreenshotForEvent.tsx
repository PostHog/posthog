import { useActions, useValues } from 'kea'

import { IconCamera } from '@posthog/icons'

import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { Spinner } from 'lib/lemon-ui/Spinner'

import { extensionMoreLogic } from '../../logics/panel/extensionMoreLogic'

/** Takes a screenshot of the page and adds it to an event definition, like the toolbar's "Screenshot for event". */
export function ExtensionScreenshotForEvent(): JSX.Element {
    const { moreState, screenshotEventName, screenshotPreview } = useValues(extensionMoreLogic)
    const { takeScreenshot, setScreenshotEventName, selectScreenshotEvent, uploadScreenshot, closeScreenshot } =
        useActions(extensionMoreLogic)
    const screenshot = moreState?.screenshot
    const selectedEvent = screenshot?.suggestions.find(({ id }) => id === screenshot.selectedEventId)

    return (
        <section className="flex flex-col gap-2">
            <h4 className="m-0 text-sm font-semibold">Screenshot for an event</h4>
            {screenshot?.result?.status === 'uploaded' && (
                <LemonBanner type="success">The screenshot is now on the event's definition.</LemonBanner>
            )}
            {screenshot?.result?.status === 'failed' && (
                <LemonBanner type="error">Couldn't add the screenshot: {screenshot.result.error}</LemonBanner>
            )}
            {screenshot?.open && screenshotPreview ? (
                <>
                    <img
                        src={screenshotPreview}
                        alt="Screenshot of the page"
                        className="w-full h-auto max-h-60 object-contain border rounded"
                    />
                    <LemonInput
                        size="small"
                        placeholder="Search for an event"
                        value={screenshotEventName}
                        onChange={setScreenshotEventName}
                        disabledReason={screenshot.uploading ? 'Uploading…' : null}
                        data-attr="toolbar-extension-screenshot-event"
                    />
                    {screenshotEventName.trim() && !selectedEvent && (
                        <div className="flex flex-col gap-px max-h-48 overflow-y-auto">
                            {screenshot.suggestionsLoading ? (
                                <div className="flex justify-center p-2">
                                    <Spinner />
                                </div>
                            ) : screenshot.suggestions.length > 0 ? (
                                screenshot.suggestions.map(({ id, name }) => (
                                    <LemonButton
                                        key={id}
                                        size="small"
                                        fullWidth
                                        onClick={() => selectScreenshotEvent(id, name)}
                                    >
                                        <span className="truncate" translate="no">
                                            {name}
                                        </span>
                                    </LemonButton>
                                ))
                            ) : (
                                <div className="p-2 text-xs text-secondary">No events match this name.</div>
                            )}
                        </div>
                    )}
                    <div className="flex flex-wrap justify-end gap-2">
                        <LemonButton
                            size="small"
                            type="secondary"
                            disabledReason={screenshot.uploading ? 'Uploading…' : null}
                            onClick={closeScreenshot}
                        >
                            Cancel
                        </LemonButton>
                        <LemonButton
                            size="small"
                            type="primary"
                            loading={screenshot.uploading}
                            disabledReason={selectedEvent ? null : 'Pick an event first'}
                            onClick={uploadScreenshot}
                            data-attr="toolbar-extension-screenshot-upload"
                        >
                            Upload
                        </LemonButton>
                    </div>
                </>
            ) : (
                <LemonButton
                    size="small"
                    type="secondary"
                    icon={<IconCamera />}
                    fullWidth
                    center
                    loading={!!screenshot?.taking}
                    disabledReason={moreState ? null : 'Connecting to the page…'}
                    onClick={takeScreenshot}
                    data-attr="toolbar-extension-screenshot-take"
                >
                    Take a screenshot of the page
                </LemonButton>
            )}
        </section>
    )
}
