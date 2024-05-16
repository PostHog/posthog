import { LemonButton, LemonInput } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'
import { teamLogic } from 'scenes/teamLogic'

import { zenHogLogic } from './zenHogLogic'

export function ZenHog(): JSX.Element {
    const [zendeskKey, setZendeskKey] = useState('')
    const { testZendeskKey, removeZendeskKey } = useActions(zenHogLogic)
    const { loading } = useValues(zenHogLogic)
    const { currentTeam } = useValues(teamLogic)
    const { updateCurrentTeam } = useActions(teamLogic)

    useEffect(() => {
        if (currentTeam?.zendesk_key) {
            setZendeskKey(currentTeam?.zendesk_key)
        }
    }, [currentTeam])

    // TODO:
    const [messageUrgent, setMessageUrgent] = useState(currentTeam?.zenhog_message_urgent || '')
    const [messageHigh, setMessageHigh] = useState(currentTeam?.zenhog_message_high || '')
    const [messageMedium, setMessageMedium] = useState(currentTeam?.zenhog_message_medium || '')
    const [messageLow, setMessageLow] = useState(currentTeam?.zenhog_message_low || '')

    return (
        <div>
            <p>Show your users their support tickets.</p>

            <div className="space-y-4 max-w-160">
                <LemonInput
                    value={zendeskKey}
                    onChange={setZendeskKey}
                    type="text"
                    placeholder={currentTeam?.zendesk_key ? '' : 'integration disabled - enter key, then Test & Save'}
                    disabled={loading}
                    onPressEnter={() => testZendeskKey(zendeskKey)}
                />
                <div className="flex items-center gap-2">
                    <LemonButton
                        type="primary"
                        disabled={!zendeskKey}
                        onClick={(e) => {
                            e.preventDefault()
                            testZendeskKey(zendeskKey)
                        }}
                        loading={loading}
                    >
                        Test & Save
                    </LemonButton>
                    <LemonButton
                        status="danger"
                        type="secondary"
                        onClick={(e) => {
                            e.preventDefault()
                            removeZendeskKey()
                            setZendeskKey('')
                        }}
                        disabled={!currentTeam?.zendesk_key}
                    >
                        Clear & Disable
                    </LemonButton>
                </div>

                <LemonInput value={messageUrgent} onChange={setMessageUrgent} disabled={loading} />
                <LemonButton
                    type="primary"
                    onClick={() => updateCurrentTeam({ zenhog_message_urgent: messageUrgent })}
                    disabled={!messageUrgent}
                    loading={loading}
                >
                    Set message for urgent tickets
                </LemonButton>
                <LemonInput value={messageHigh} onChange={setMessageHigh} disabled={loading} />
                <LemonButton
                    type="primary"
                    onClick={() => updateCurrentTeam({ zenhog_message_high: messageHigh })}
                    disabled={!messageHigh}
                    loading={loading}
                >
                    Set message for high priority tickets
                </LemonButton>
                <LemonInput value={messageMedium} onChange={setMessageMedium} disabled={loading} />
                <LemonButton
                    type="primary"
                    onClick={() => updateCurrentTeam({ zenhog_message_medium: messageMedium })}
                    disabled={!messageMedium}
                    loading={loading}
                >
                    Set message for medium priority tickets
                </LemonButton>
                <LemonInput value={messageLow} onChange={setMessageLow} disabled={loading} />
                <LemonButton
                    type="primary"
                    onClick={() => updateCurrentTeam({ zenhog_message_low: messageLow })}
                    disabled={!messageLow}
                    loading={loading}
                >
                    Set message for low priority tickets
                </LemonButton>
            </div>
        </div>
    )
}
