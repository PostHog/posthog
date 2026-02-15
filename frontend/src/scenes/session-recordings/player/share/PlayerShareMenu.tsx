import { useActions, useValues } from 'kea'

import { IconExternal, IconGlobe, IconShare, IconShield } from '@posthog/icons'
import { LemonButton, LemonMenu } from '@posthog/lemon-ui'

import { newInternalTab } from 'lib/utils/newInternalTab'
import { sessionPlayerModalLogic } from 'scenes/session-recordings/player/modal/sessionPlayerModalLogic'
import { sessionRecordingPlayerLogic } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'
import { openPlayerShareDialog } from 'scenes/session-recordings/player/share/PlayerShare'
import { PlayerShareLogicProps } from 'scenes/session-recordings/player/share/playerShareLogic'
import { urls } from 'scenes/urls'

export function PlayerShareMenu(): JSX.Element {
    const { sessionRecordingId, logicProps } = useValues(sessionRecordingPlayerLogic)
    const { setPause, setIsFullScreen } = useActions(sessionRecordingPlayerLogic)
    const { closeSessionPlayer } = useActions(sessionPlayerModalLogic())

    const getCurrentPlayerTime = (): number => {
        // NOTE: We pull this value at call time as otherwise it would trigger re-renders if pulled from the hook
        const playerTime = sessionRecordingPlayerLogic.findMounted(logicProps)?.values.currentPlayerTime || 0
        return Math.floor(playerTime / 1000)
    }

    const onShare = (shareType: PlayerShareLogicProps['shareType']): void => {
        setPause()
        setIsFullScreen(false)
        openPlayerShareDialog({
            seconds: getCurrentPlayerTime(),
            id: sessionRecordingId,
            shareType,
        })
    }

    const onOpenInNewTab = (): void => {
        if (!sessionRecordingId) {
            return
        }
        setPause()
        setIsFullScreen(false)
        closeSessionPlayer()
        newInternalTab(urls.replaySingle(sessionRecordingId))
    }

    return (
        <LemonMenu
            items={[
                {
                    label: 'Open in new tab',
                    icon: <IconExternal />,
                    onClick: onOpenInNewTab,
                    disabledReason: !sessionRecordingId ? 'Recording not loaded yet' : undefined,
                    'data-attr': 'open-in-new-tab',
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
                    'data-attr': 'share-public-link',
                },
                {
                    label: 'Share to Linear',
                    icon: <IconExternal />,
                    onClick: () => onShare('linear'),
                    'data-attr': 'share-to-linear',
                },
                {
                    label: 'Share to Github Issues',
                    icon: <IconExternal />,
                    onClick: () => onShare('github'),
                    'data-attr': 'share-to-github',
                },
            ]}
            buttonSize="xsmall"
        >
            <LemonButton size="xsmall" icon={<IconShare />} data-attr="session-recording-share-button">
                Share
            </LemonButton>
        </LemonMenu>
    )
}
