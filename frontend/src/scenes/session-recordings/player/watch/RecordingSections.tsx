import { useActions, useValues } from 'kea'

import { LemonCollapse } from '@posthog/lemon-ui'

import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { WatchPanelSection, playerSettingsLogic } from 'scenes/session-recordings/player/playerSettingsLogic'
import { sessionRecordingPlayerLogic } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'
import { PlayerSidebarLinkedIssuesTab } from 'scenes/session-recordings/player/sidebar/PlayerSidebarLinkedIssuesTab'

export function RecordingSections(): JSX.Element | null {
    const { sessionPlayerMetaData } = useValues(sessionRecordingPlayerLogic)
    const { getIntegrationsByKind } = useValues(integrationsLogic)
    const { watchPanelOpenSections } = useValues(playerSettingsLogic)
    const { toggleWatchPanelSection } = useActions(playerSettingsLogic)

    const showLinkedIssues =
        getIntegrationsByKind(['linear', 'github', 'gitlab', 'jira']).length > 0 ||
        (sessionPlayerMetaData?.external_references ?? []).length > 0

    const panels = [
        showLinkedIssues && {
            key: 'linked-issues' as WatchPanelSection,
            header: 'Linked issues',
            content: <PlayerSidebarLinkedIssuesTab />,
            dataAttr: 'watch-panel-section-linked-issues',
        },
    ].filter((panel): panel is Exclude<typeof panel, false> => !!panel)

    if (panels.length === 0) {
        return null
    }
    const sectionKeys = panels.map((panel) => panel.key)
    const activeKeys = watchPanelOpenSections.filter((section) => sectionKeys.includes(section))

    return (
        <LemonCollapse
            size="small"
            multiple
            panels={panels}
            activeKeys={activeKeys}
            onChange={(next: WatchPanelSection[]) => {
                for (const key of sectionKeys) {
                    if (activeKeys.includes(key) !== next.includes(key)) {
                        toggleWatchPanelSection(key)
                    }
                }
            }}
        />
    )
}
