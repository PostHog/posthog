import { useActions, useValues } from 'kea'
import { useId, useState } from 'react'

import { IconChevronRight, IconGear } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { LemonLabel } from 'lib/lemon-ui/LemonLabel'
import { LemonSelect } from 'lib/lemon-ui/LemonSelect'
import { cn } from 'lib/utils/css-classes'

import { canonicalizeUiHost } from '~/toolbar/shared/toolbarConfigLogic'

import { extensionPanelLogic } from '../../logics/panel/extensionPanelLogic'

const CLOUD_HOSTS = ['https://us.posthog.com', 'https://eu.posthog.com']
const CUSTOM_HOST = 'custom'

export function ExtensionPanelSettings(): JSX.Element {
    const { uiHost, user, projectSwitchFailed, settingsExpanded } = useValues(extensionPanelLogic)
    const { setUiHost, switchProject, setSettingsExpanded } = useActions(extensionPanelLogic)
    const settingsId = useId()
    const isCloudHost = CLOUD_HOSTS.includes(uiHost)
    const [editingCustomHost, setEditingCustomHost] = useState(false)
    const [customHost, setCustomHost] = useState(isCloudHost ? '' : uiHost)
    const canonicalCustomHost = canonicalizeUiHost(customHost)
    const host = new URL(uiHost).host

    return (
        <div className="mt-auto flex flex-col gap-2 border-t pt-2">
            <LemonButton
                size="xsmall"
                fullWidth
                icon={<IconGear />}
                sideIcon={
                    <IconChevronRight
                        className={cn(
                            'transition-transform motion-reduce:transition-none',
                            settingsExpanded && 'rotate-90'
                        )}
                    />
                }
                onClick={() => setSettingsExpanded(!settingsExpanded)}
                aria-expanded={settingsExpanded}
                aria-controls={settingsExpanded ? settingsId : undefined}
                data-attr="toolbar-extension-settings-toggle"
            >
                <span className="truncate text-xs text-secondary">{user ? `${user.team.name} · ${host}` : host}</span>
            </LemonButton>
            {settingsExpanded ? (
                <div id={settingsId} className="flex flex-col gap-2">
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
                            {projectSwitchFailed ? (
                                <div className="text-danger text-xs">Couldn't switch the project. Try again.</div>
                            ) : null}
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
            ) : null}
        </div>
    )
}
