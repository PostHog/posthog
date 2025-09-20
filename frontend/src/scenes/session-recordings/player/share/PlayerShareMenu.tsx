import { useActions, useValues } from 'kea'

import { IconExternal, IconGlobe, IconShare, IconShield } from '@posthog/icons'
import { LemonButton, LemonMenu } from '@posthog/lemon-ui'

import { sessionRecordingPlayerLogic } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'
import { openPlayerShareDialog } from 'scenes/session-recordings/player/share/PlayerShare'
import { PlayerShareLogicProps } from 'scenes/session-recordings/player/share/playerShareLogic'

export function PlayerShareMenu(): JSX.Element {
    const { sessionRecordingId, logicProps } = useValues(sessionRecordingPlayerLogic)
    const { setPause, setIsFullScreen } = useActions(sessionRecordingPlayerLogic)

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

    return (
        <LemonMenu
            items={[
                {
                    label: 'Share private link',
                    icon: <IconShield />,
                    onClick: () => onShare('private'),
                },
                {
                    label: 'Share public link',
                    icon: <IconGlobe />,
                    onClick: () => onShare('public'),
                },
                {
                    label: 'Share to Linear',
                    icon: <IconExternal />,
                    onClick: () => onShare('linear'),
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
