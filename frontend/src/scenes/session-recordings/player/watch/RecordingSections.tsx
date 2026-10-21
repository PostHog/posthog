import { useActions, useValues } from 'kea'

import { LemonCollapse } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { WatchPanelSection, playerSettingsLogic } from 'scenes/session-recordings/player/playerSettingsLogic'
import { sessionRecordingPlayerLogic } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'
import { PlayerSidebarLinkedIssuesTab } from 'scenes/session-recordings/player/sidebar/PlayerSidebarLinkedIssuesTab'
import { PlayerSidebarPersonRecordingsTab } from 'scenes/session-recordings/player/sidebar/PlayerSidebarPersonRecordingsTab'

/** The person's other sessions and linked issues, collapsed under the summary; same visibility gates as the sidebar tabs. */
export function RecordingSections(): JSX.Element | null {
    const { sessionPlayerMetaData } = useValues(sessionRecordingPlayerLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const { getIntegrationsByKind } = useValues(integrationsLogic)
    const { watchPanelOpenSections } = useValues(playerSettingsLogic)
    const { toggleWatchPanelSection } = useActions(playerSettingsLogic)

    const showSessions =
        !!featureFlags[FEATURE_FLAGS.REPLAY_PLAYER_PERSON_SESSIONS_TAB] && !!sessionPlayerMetaData?.person
    const showLinkedIssues =
        getIntegrationsByKind(['linear', 'github', 'gitlab', 'jira']).length > 0 ||
        (sessionPlayerMetaData?.external_references ?? []).length > 0

    const panels = [
        showSessions && {
            key: 'sessions' as WatchPanelSection,
            header: 'Sessions',
            content: <PlayerSidebarPersonRecordingsTab />,
            dataAttr: 'watch-panel-section-sessions',
        },
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
