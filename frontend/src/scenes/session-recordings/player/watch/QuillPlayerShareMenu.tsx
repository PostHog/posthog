import { useActions, useValues } from 'kea'

import { IconExternal, IconGlobe, IconShare, IconShield } from '@posthog/icons'
import { Button, DropdownMenu, DropdownMenuContent, DropdownMenuTrigger } from '@posthog/quill'

import { useFloatingContainer } from 'lib/hooks/useFloatingContainerContext'
import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'
import { newInternalTab } from 'lib/utils/newInternalTab'
import { sessionPlayerModalLogic } from 'scenes/session-recordings/player/modal/sessionPlayerModalLogic'
import { sessionRecordingPlayerLogic } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'
import { openPlayerShareDialog } from 'scenes/session-recordings/player/share/PlayerShare'
import { PlayerShareLogicProps } from 'scenes/session-recordings/player/share/playerShareLogic'
import { QuillMenuItems } from 'scenes/session-recordings/playlist/QuillMenuItems'
import { urls } from 'scenes/urls'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

export function QuillPlayerShareMenu({ filled = false }: { filled?: boolean }): JSX.Element {
    const { sessionRecordingId, logicProps } = useValues(sessionRecordingPlayerLogic)
    const { setPause, setIsFullScreen } = useActions(sessionRecordingPlayerLogic)
    const { closeSessionPlayer } = useActions(sessionPlayerModalLogic())
    const floatingContainer = useFloatingContainer()
    const sharingDisabledReason = getAccessControlDisabledReason(
        AccessControlResourceType.SharingConfiguration,
        AccessControlLevel.Viewer
    )
    const notLoadedReason = !sessionRecordingId ? 'Recording not loaded yet' : undefined

    // Read at call time: subscribing to the player time would re-render the menu on every tick.
    const getCurrentPlayerTime = (): number => {
        const playerTime = sessionRecordingPlayerLogic.findMounted(logicProps)?.values.currentPlayerTime || 0
        return Math.floor(playerTime / 1000)
    }

    const onShare = (shareType: PlayerShareLogicProps['shareType']): void => {
        setPause()
        setIsFullScreen(false)
        openPlayerShareDialog({ seconds: getCurrentPlayerTime(), id: sessionRecordingId, shareType })
    }

    const onOpenInNewTab = (): void => {
        setPause()
        setIsFullScreen(false)
        closeSessionPlayer()
        newInternalTab(urls.replaySingle(sessionRecordingId))
    }

    const onOpenInBrowserTab = (): void => {
        const path = urls.replaySingle(sessionRecordingId)
        const timestamp = getCurrentPlayerTime()
        const separator = path.includes('?') ? '&' : '?'
        window.open(
            `${window.location.origin}${path}${timestamp ? `${separator}t=${timestamp}` : ''}`,
            '_blank',
            'noopener,noreferrer'
        )
    }

    return (
        <DropdownMenu>
            <DropdownMenuTrigger
                render={
                    <Button
                        size={filled ? 'icon' : 'icon-sm'}
                        variant={filled ? 'secondary' : 'default'}
                        tooltip="Share"
                        aria-label="Share"
                        data-attr="session-recording-share-button"
                    />
                }
            >
                <IconShare />
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" container={floatingContainer}>
                <QuillMenuItems
                    items={[
                        {
                            label: 'Open in new tab',
                            icon: <IconExternal />,
                            onClick: onOpenInNewTab,
                            disabledReason: notLoadedReason,
                            'data-attr': 'open-in-new-tab',
                        },
                        {
                            label: 'Open in new browser tab',
                            icon: <IconExternal />,
                            onClick: onOpenInBrowserTab,
                            disabledReason: notLoadedReason,
                            'data-attr': 'open-in-browser-tab',
                        },
                        {
                            label: 'Share private link',
                            icon: <IconShield />,
                            onClick: () => onShare('private'),
                            'data-attr': 'share-private-link',
                        },
                        {
                            label: 'Share public link',
                            icon: <IconGlobe />,
                            onClick: () => onShare('public'),
                            disabledReason: sharingDisabledReason ?? undefined,
                            'data-attr': 'share-public-link',
                        },
                    ]}
                />
            </DropdownMenuContent>
        </DropdownMenu>
    )
}
