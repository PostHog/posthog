import { useActions, useValues } from 'kea'

import { IconCheck, IconRefresh, IconX } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { Spinner } from 'lib/lemon-ui/Spinner'

import { extensionMoreLogic } from '../../logics/panel/extensionMoreLogic'
import { NoPagePosthogBanner } from '../panel/NoPagePosthogBanner'

function DebugInfoRow({ label, value }: { label: string; value: string | boolean | number | null }): JSX.Element {
    return (
        <>
            <dt className="text-secondary">{label}</dt>
            <dd className="m-0 min-w-0 truncate text-right" translate="no">
                {typeof value === 'boolean' ? (
                    value ? (
                        <IconCheck className="text-success" aria-label="On" />
                    ) : (
                        <IconX className="text-danger" aria-label="Off" />
                    )
                ) : (
                    (value ?? 'Unknown')
                )}
            </dd>
        </>
    )
}

/** The posthog-js settings the toolbar's "Debug info" menu shows. */
export function ExtensionDebugInfo(): JSX.Element {
    const { moreState } = useValues(extensionMoreLogic)
    const { sendMoreCommand, openSessionRecording } = useActions(extensionMoreLogic)
    const debugInfo = moreState?.debugInfo ?? null
    const loading = !moreState || moreState.debugInfoLoading

    return (
        <section className="flex flex-col gap-2">
            <div className="flex items-center justify-between gap-2">
                <h4 className="m-0 text-sm font-semibold">Debug info</h4>
                <LemonButton
                    size="xsmall"
                    icon={<IconRefresh />}
                    tooltip="Read the page's settings again"
                    loading={loading}
                    onClick={() => sendMoreCommand({ type: 'reload-debug-info' })}
                    data-attr="toolbar-extension-debug-info-reload"
                />
            </div>
            {debugInfo ? (
                <>
                    <dl className="m-0 grid grid-cols-[auto_minmax(0,1fr)] gap-x-4 gap-y-1 text-xs">
                        <DebugInfoRow label="posthog-js version" value={debugInfo.version} />
                        <DebugInfoRow label="API host" value={debugInfo.apiHost} />
                        <DebugInfoRow label="UI host" value={debugInfo.uiHost ?? 'Not set'} />
                        <DebugInfoRow label="Autocapture" value={debugInfo.autocapture} />
                        <DebugInfoRow label="Rageclicks" value={debugInfo.rageclicks} />
                        <DebugInfoRow label="Dead clicks" value={debugInfo.deadClicks} />
                        <DebugInfoRow label="Heatmaps" value={debugInfo.heatmaps} />
                        <DebugInfoRow label="Surveys" value={debugInfo.surveysCount} />
                        <DebugInfoRow label="Session recording" value={debugInfo.sessionRecordingStarted} />
                        <DebugInfoRow label="Session recording status" value={debugInfo.sessionRecordingStatus} />
                    </dl>
                    <LemonButton
                        size="small"
                        type="secondary"
                        fullWidth
                        center
                        disabledReason={
                            debugInfo.sessionReplayUrl ? null : "The page's posthog-js has no session recording URL"
                        }
                        onClick={() => debugInfo.sessionReplayUrl && openSessionRecording(debugInfo.sessionReplayUrl)}
                        data-attr="toolbar-extension-view-session-recording"
                    >
                        View current session recording
                    </LemonButton>
                </>
            ) : loading ? (
                <div className="flex justify-center p-2">
                    <Spinner />
                </div>
            ) : (
                <NoPagePosthogBanner consequence="there is no debug info." />
            )}
        </section>
    )
}
