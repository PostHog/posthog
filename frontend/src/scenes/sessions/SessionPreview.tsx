import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { LemonButton, Link, Tooltip } from '@posthog/lemon-ui'

import { PropertiesTable } from 'lib/components/PropertiesTable'
import { ScrollableShadows } from 'lib/components/ScrollableShadows/ScrollableShadows'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { IconOpenInNew } from 'lib/lemon-ui/icons'
import { IconPlayCircle } from 'lib/lemon-ui/icons'
import { urls } from 'scenes/urls'

import { PropertyDefinitionType } from '~/types'

import { sessionProfileLogic } from './sessionProfileLogic'

export interface SessionPreviewProps {
    sessionId: string
    onClose?: () => void
}

export function SessionPreview({ sessionId, onClose }: SessionPreviewProps): JSX.Element | null {
    const { loadSessionData } = useActions(sessionProfileLogic({ sessionId }))
    const { sessionData, sessionDataLoading, hasRecording, sessionProperties } = useValues(
        sessionProfileLogic({ sessionId })
    )

    useEffect(() => {
        loadSessionData()
    }, [loadSessionData, sessionId])

    if (sessionDataLoading && !sessionData) {
        return (
            <div className="p-4 flex items-center justify-center">
                <Spinner />
            </div>
        )
    }

    if (!sessionData) {
        return (
            <div className="p-4 max-w-160">
                <h4 className="mb-1">Session not found</h4>
                <p className="text-muted mb-0">This session may have expired or been deleted.</p>
            </div>
        )
    }

    const profileUrl = urls.sessionProfile(sessionId)

    return (
        <div className="flex flex-col overflow-hidden max-h-96 max-w-160 gap-2">
            <div className="flex items-center justify-between min-h-10 px-2 pt-2">
                <Link to={profileUrl} className="font-semibold font-mono text-sm truncate flex-1">
                    {sessionId}
                </Link>
                {hasRecording && (
                    <Tooltip title="Watch recording">
                        <LemonButton
                            size="small"
                            icon={<IconPlayCircle />}
                            to={urls.replaySingle(sessionId)}
                            onClick={() => onClose?.()}
                        />
                    </Tooltip>
                )}
            </div>

            <ScrollableShadows direction="vertical">
                <PropertiesTable
                    properties={sessionProperties || {}}
                    type={PropertyDefinitionType.Session}
                    sortProperties
                    embedded={false}
                />
            </ScrollableShadows>

            <div className="border-t px-2 py-2">
                <LemonButton
                    type="secondary"
                    size="small"
                    fullWidth
                    center
                    to={profileUrl}
                    onClick={() => onClose?.()}
                    sideIcon={<IconOpenInNew />}
                >
                    View session details
                </LemonButton>
            </div>
        </div>
    )
}
