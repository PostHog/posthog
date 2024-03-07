import { IconDashboard, IconSearch, IconTerminal } from '@posthog/icons'
import clsx from 'clsx'
import { useValues } from 'kea'
import { IconUnverifiedEvent } from 'lib/lemon-ui/icons'

import { SessionRecordingPlayerTab } from '~/types'

import { sessionRecordingPlayerLogic } from '../sessionRecordingPlayerLogic'
import { playerInspectorLogic } from './playerInspectorLogic'

const TabToIcon = {
    [SessionRecordingPlayerTab.ALL]: IconSearch,
    [SessionRecordingPlayerTab.EVENTS]: IconUnverifiedEvent,
    [SessionRecordingPlayerTab.CONSOLE]: IconTerminal,
    [SessionRecordingPlayerTab.NETWORK]: IconDashboard,
}

export function PlayerInspectorPreview(props: { onClick: () => void }): JSX.Element {
    const { logicProps } = useValues(sessionRecordingPlayerLogic)
    const inspectorLogic = playerInspectorLogic(logicProps)

    const { tab } = useValues(inspectorLogic)

    const tabs = [
        SessionRecordingPlayerTab.ALL,
        SessionRecordingPlayerTab.EVENTS,
        SessionRecordingPlayerTab.CONSOLE,
        SessionRecordingPlayerTab.NETWORK,
    ]

    return (
        <div className="PlayerInspectorPreview bg-side p-2 space-y-2 flex flex-col" onClick={props.onClick}>
            {tabs.map((tabId) => {
                const TabIcon = TabToIcon[tabId]
                return (
                    <div
                        key={tabId}
                        className={clsx(
                            'rounded p-1 w-6 h-6 flex items-center justify-center relative',
                            tab === tabId && 'bg-primary-alt-highlight'
                        )}
                    >
                        <TabIcon className="text-lg text-primary-alt" />
                    </div>
                )
            })}
        </div>
    )
}
