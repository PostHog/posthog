import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { LemonLabel } from 'lib/lemon-ui/LemonLabel'
import { LemonSelect } from 'lib/lemon-ui/LemonSelect'

import { canonicalizeUiHost } from '~/toolbar/toolbarConfigLogic'

import { extensionPopupLogic } from './extensionPopupLogic'

const CLOUD_HOSTS = ['https://us.posthog.com', 'https://eu.posthog.com']
const CUSTOM_HOST = 'custom'

export function ExtensionPopupSettings(): JSX.Element {
    const { uiHost, user } = useValues(extensionPopupLogic)
    const { setUiHost, switchProject } = useActions(extensionPopupLogic)
    const isCloudHost = CLOUD_HOSTS.includes(uiHost)
    const [editingCustomHost, setEditingCustomHost] = useState(false)
    const [customHost, setCustomHost] = useState(isCloudHost ? '' : uiHost)
    const canonicalCustomHost = canonicalizeUiHost(customHost)

    return (
        <div className="flex flex-col gap-2 border-t pt-3">
            {user ? (
                <>
                    <LemonLabel>Project</LemonLabel>
                    <LemonSelect
                        size="small"
                        fullWidth
                        value={user.team.id}
                        onChange={(teamId) => switchProject(teamId)}
                        options={user.organization.teams.map((team) => ({ value: team.id, label: team.name }))}
                        data-attr="toolbar-extension-project"
                    />
                </>
            ) : null}
            <LemonLabel>PostHog host</LemonLabel>
            <LemonSelect
                size="small"
                fullWidth
                value={editingCustomHost || !isCloudHost ? CUSTOM_HOST : uiHost}
                onChange={(value) => {
                    setEditingCustomHost(value === CUSTOM_HOST)
                    if (value !== CUSTOM_HOST) {
                        setUiHost(value)
                    }
                }}
                options={[
                    { value: 'https://us.posthog.com', label: 'PostHog Cloud US' },
                    { value: 'https://eu.posthog.com', label: 'PostHog Cloud EU' },
                    { value: CUSTOM_HOST, label: isCloudHost ? 'Self-hosted' : new URL(uiHost).host },
                ]}
                data-attr="toolbar-extension-host"
            />
            {editingCustomHost ? (
                <div className="flex gap-2">
                    <LemonInput
                        size="small"
                        className="flex-1"
                        placeholder="https://posthog.example.com"
                        value={customHost}
                        onChange={setCustomHost}
                    />
                    <LemonButton
                        size="small"
                        type="primary"
                        disabledReason={canonicalCustomHost ? null : 'Enter the address of your PostHog app'}
                        onClick={() => {
                            if (canonicalCustomHost) {
                                setUiHost(canonicalCustomHost)
                                setEditingCustomHost(false)
                            }
                        }}
                        data-attr="toolbar-extension-save-host"
                    >
                        Save
                    </LemonButton>
                </div>
            ) : null}
        </div>
    )
}
