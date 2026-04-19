import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton, LemonInput } from '@posthog/lemon-ui'

import { teamLogic } from 'scenes/teamLogic'

import { supportSettingsLogic } from './supportSettingsLogic'

export function ConversationsPublicTokenSetting(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const { generateNewToken } = useActions(supportSettingsLogic)

    if (!currentTeam?.conversations_enabled) {
        return <p className="text-muted text-sm">Enable conversations API first.</p>
    }

    return (
        <div className="space-y-2">
            <div className="flex items-center gap-4 justify-between">
                <div>
                    <label className="font-medium">Public token</label>
                    <p className="text-xs text-muted-alt">
                        Automatically generated token used to authenticate widget requests.
                    </p>
                </div>
                <div className="flex gap-2 flex-1">
                    <LemonInput
                        value={
                            currentTeam?.conversations_settings?.widget_public_token ||
                            'Token will be auto-generated on save'
                        }
                        disabledReason="Read-only after generation"
                        fullWidth
                    />
                    {currentTeam?.conversations_settings?.widget_public_token && (
                        <LemonButton type="secondary" status="danger" onClick={generateNewToken}>
                            Regenerate
                        </LemonButton>
                    )}
                </div>
            </div>
            <LemonBanner type="warning">Only regenerate if you suspect it has been exposed or compromised.</LemonBanner>
        </div>
    )
}
