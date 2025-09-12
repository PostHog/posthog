import { useActions, useValues } from 'kea'

import { IconRefresh, IconX } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonModal } from 'lib/lemon-ui/LemonModal'

import { streamlitAppsLogic } from './streamlitAppsLogic'

export function StreamlitAppViewer(): JSX.Element | null {
    const { openApp } = useValues(streamlitAppsLogic)
    const { closeApp } = useActions(streamlitAppsLogic)

    if (!openApp) {
        return null
    }

    // For debugging, let's try the internal URL directly
    const appUrl = openApp.internal_url || `http://localhost:${openApp.port || 8501}`

    return (
        <LemonModal
            isOpen={!!openApp}
            onClose={closeApp}
            title={openApp.name}
            width="90%"
            maxWidth="1200px"
            footer={
                <div className="flex justify-between items-center w-full">
                    <div className="text-sm text-muted-foreground">
                        <strong>Status:</strong> {openApp.container_status} |<strong> Port:</strong>{' '}
                        {openApp.port || 'N/A'} |<strong> Container ID:</strong>{' '}
                        {openApp.container_id || 'Not deployed yet'}
                        {openApp.last_accessed && (
                            <>
                                {' '}
                                | <strong> Last accessed:</strong> {new Date(openApp.last_accessed).toLocaleString()}
                            </>
                        )}
                        <br />
                        <strong>URL:</strong> {appUrl}
                    </div>
                    <div className="flex gap-2">
                        <LemonButton
                            size="small"
                            onClick={() => {
                                // Open in new tab for debugging
                                window.open(appUrl, '_blank')
                            }}
                        >
                            Open in New Tab
                        </LemonButton>
                        <LemonButton
                            icon={<IconRefresh />}
                            size="small"
                            onClick={() => {
                                // Refresh the iframe
                                const iframe = document.getElementById('streamlit-iframe') as HTMLIFrameElement
                                if (iframe) {
                                    iframe.src = iframe.src
                                }
                            }}
                        >
                            Refresh
                        </LemonButton>
                        <LemonButton icon={<IconX />} size="small" onClick={closeApp}>
                            Close
                        </LemonButton>
                    </div>
                </div>
            }
        >
            <div className="w-full h-[70vh] min-h-[500px]">
                <iframe
                    id="streamlit-iframe"
                    src={appUrl}
                    className="w-full h-full border rounded"
                    title={openApp.name}
                    sandbox="allow-scripts allow-same-origin allow-forms allow-popups allow-popups-to-escape-sandbox"
                />
            </div>
        </LemonModal>
    )
}
