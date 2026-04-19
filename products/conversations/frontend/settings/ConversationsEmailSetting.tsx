import { useValues } from 'kea'

import { teamLogic } from 'scenes/teamLogic'

import { EmailSection } from './EmailSection'

export function ConversationsEmailSetting(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)

    if (!currentTeam?.conversations_enabled) {
        return <p className="text-muted text-sm">Enable conversations API first.</p>
    }

    return <EmailSection />
}
