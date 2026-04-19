import { useValues } from 'kea'

import { teamLogic } from 'scenes/teamLogic'

import { SlackSection } from './SlackSection'

export function ConversationsSlackSetting(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)

    if (!currentTeam?.conversations_enabled) {
        return <p className="text-muted text-sm">Enable conversations API first.</p>
    }

    return <SlackSection />
}
