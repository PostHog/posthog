import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { LemonButton, LemonCard, LemonInput, LemonSelect, LemonSwitch, LemonTag, Link } from '@posthog/lemon-ui'

import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'
import { rolesLogic } from 'scenes/settings/organization/Permissions/Roles/rolesLogic'
import { urls } from 'scenes/urls'

import { SceneSection } from '~/layout/scenes/components/SceneSection'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

import type { TicketTopicOverrideApi, TicketTopicOverrideKindEnumApi } from '../../generated/api.schemas'
import { ticketPatternSettingsLogic } from './ticketPatternSettingsLogic'

const WINDOW_OPTIONS = [
    { value: 15, label: '15 minutes' },
    { value: 30, label: '30 minutes' },
    { value: 60, label: '1 hour' },
    { value: 180, label: '3 hours' },
    { value: 1440, label: '24 hours' },
]

const COUNT_OPTIONS = [3, 4, 5, 6, 8, 10].map((n) => ({ value: n, label: String(n) }))

function OverrideList({
    kind,
    title,
    description,
    placeholder,
}: {
    kind: TicketTopicOverrideKindEnumApi
    title: string
    description: string
    placeholder: string
}): JSX.Element {
    const { overrides, overridesLoading, overrideDrafts, addingKinds } = useValues(ticketPatternSettingsLogic)
    const { addOverride, removeOverride, setOverrideDraft } = useActions(ticketPatternSettingsLogic)
    const rows = overrides.filter((o: TicketTopicOverrideApi) => o.kind === kind)
    const draft = overrideDrafts[kind] ?? ''
    const adding = !!addingKinds[kind]
    // The list endpoint admits a ticket viewer, but writing an override needs editor, so a viewer
    // would otherwise get live controls and a 403 they cannot act on.
    const writeDisabledReason =
        getAccessControlDisabledReason(AccessControlResourceType.Ticket, AccessControlLevel.Editor) ?? undefined

    const submit = (): void => {
        const topic = draft.trim()
        if (topic && !adding) {
            addOverride(kind, topic)
        }
    }

    return (
        <LemonCard hoverEffect={false} className="flex flex-col gap-y-3 max-w-[800px] px-4 py-3">
            <div>
                <label className="font-medium">{title}</label>
                <p className="text-xs text-muted-alt mb-0">{description}</p>
            </div>
            <div className="flex flex-wrap gap-2">
                {rows.map((o) => (
                    <LemonTag key={o.id} closable={!writeDisabledReason} onClose={() => removeOverride(o.id)}>
                        {o.topic}
                    </LemonTag>
                ))}
                {rows.length === 0 && !overridesLoading ? <span className="text-muted text-sm">None yet</span> : null}
            </div>
            <div className="flex flex-wrap gap-2 items-center">
                <LemonInput
                    size="small"
                    className="min-w-60"
                    placeholder={placeholder}
                    value={draft}
                    onChange={(value) => setOverrideDraft(kind, value)}
                    onPressEnter={submit}
                    disabledReason={writeDisabledReason}
                    data-attr={`ticket-pattern-override-${kind}-input`}
                />
                <LemonButton
                    size="small"
                    type="secondary"
                    onClick={submit}
                    loading={adding}
                    disabledReason={writeDisabledReason ?? (draft.trim() ? undefined : 'Enter a topic first')}
                    data-attr={`ticket-pattern-override-${kind}-add`}
                >
                    Add
                </LemonButton>
            </div>
        </LemonCard>
    )
}

export function TicketPatternsSection(): JSX.Element {
    const { settings, saving } = useValues(ticketPatternSettingsLogic)
    const { updateSettings } = useActions(ticketPatternSettingsLogic)
    const { roles } = useValues(rolesLogic)
    const { loadRoles } = useActions(rolesLogic)

    useEffect(() => {
        loadRoles()
    }, [loadRoles])

    return (
        <>
            <SceneSection
                title="Ticket patterns"
                className="my-8"
                description="Detection looks for several different customers raising the same topic inside a short window and opens a pattern for your team to review. No AI is involved."
            >
                <LemonCard hoverEffect={false} className="flex flex-col gap-y-3 max-w-[800px] px-4 py-3">
                    <div className="flex items-center gap-4 justify-between">
                        <div>
                            <label className="font-medium">Detect ticket patterns</label>
                            <p className="text-xs text-muted-alt mb-0">
                                Runs every 15 minutes on the tickets in this project. Open patterns appear above the
                                ticket list and on the <Link to={urls.supportPatterns()}>Patterns tab</Link>.
                            </p>
                        </div>
                        <LemonSwitch
                            checked={settings.enabled}
                            onChange={(enabled) => updateSettings({ enabled })}
                            loading={saving}
                            data-attr="ticket-pattern-detection-toggle"
                        />
                    </div>
                </LemonCard>
            </SceneSection>

            {settings.enabled ? (
                <>
                    <SceneSection
                        title="Threshold"
                        titleSize="sm"
                        className="my-8"
                        description="A pattern opens when at least this many tickets share a topic inside the window. The customer count is a starting point. Detection raises it for a topic that comes up most days or that you have dismissed before, lowers it for one you have confirmed, and never goes below three. Lower numbers catch smaller bursts and raise the chance of a false alarm."
                    >
                        <LemonCard hoverEffect={false} className="flex flex-col gap-y-3 max-w-[800px] px-4 py-3">
                            <div className="flex flex-wrap gap-4">
                                <div className="flex flex-col gap-1">
                                    <label className="text-sm font-medium">Different customers</label>
                                    <LemonSelect
                                        size="small"
                                        value={settings.minRequesters}
                                        options={COUNT_OPTIONS}
                                        onChange={(minRequesters) => updateSettings({ minRequesters })}
                                        disabledReason={saving ? 'Saving' : undefined}
                                    />
                                </div>
                                <div className="flex flex-col gap-1">
                                    <label className="text-sm font-medium">Tickets</label>
                                    <LemonSelect
                                        size="small"
                                        value={settings.minTickets}
                                        options={COUNT_OPTIONS}
                                        onChange={(minTickets) => updateSettings({ minTickets })}
                                        disabledReason={saving ? 'Saving' : undefined}
                                    />
                                </div>
                                <div className="flex flex-col gap-1">
                                    <label className="text-sm font-medium">Window</label>
                                    <LemonSelect
                                        size="small"
                                        value={settings.windowMinutes}
                                        options={WINDOW_OPTIONS}
                                        onChange={(windowMinutes) => updateSettings({ windowMinutes })}
                                        disabledReason={saving ? 'Saving' : undefined}
                                    />
                                </div>
                            </div>
                        </LemonCard>
                    </SceneSection>

                    <SceneSection
                        title="Who to tell"
                        titleSize="sm"
                        className="my-8"
                        description="Every open pattern shows in the support inbox. Choose a role to also send an in-app notification. Slack uses the alert channel in Slack settings."
                    >
                        <LemonCard hoverEffect={false} className="flex flex-col gap-y-3 max-w-[800px] px-4 py-3">
                            <div className="flex flex-col gap-1 max-w-80">
                                <label className="text-sm font-medium">Notify role</label>
                                <LemonSelect
                                    size="small"
                                    value={settings.notifyRoleId}
                                    options={[
                                        { value: null, label: 'Nobody' },
                                        ...roles.map((role) => ({ value: role.id, label: role.name })),
                                    ]}
                                    onChange={(notifyRoleId) => updateSettings({ notifyRoleId })}
                                    disabledReason={saving ? 'Saving' : undefined}
                                    data-attr="ticket-pattern-notify-role"
                                />
                            </div>
                        </LemonCard>
                    </SceneSection>

                    <SceneSection
                        title="Topics"
                        titleSize="sm"
                        className="my-8"
                        description="Tell detection about topics it gets wrong. Topics are matched after the same normalization applied to ticket text, so 'Login failures' and 'login failure' are the same."
                    >
                        <div className="flex flex-col gap-3">
                            <OverrideList
                                kind="mute"
                                title="Never alert on"
                                description="Topics that always look like a burst but never are, such as a scheduled report or a newsletter reply."
                                placeholder="Weekly digest"
                            />
                            <OverrideList
                                kind="watch"
                                title="Alert sooner on"
                                description="Topics that open as soon as three different customers raise them. The ticket minimum above still applies."
                                placeholder="Data loss"
                            />
                        </div>
                    </SceneSection>
                </>
            ) : null}
        </>
    )
}
