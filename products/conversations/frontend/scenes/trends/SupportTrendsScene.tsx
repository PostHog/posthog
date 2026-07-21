import { useActions, useValues } from 'kea'

import {
    LemonBanner,
    LemonButton,
    LemonDialog,
    LemonInput,
    LemonLabel,
    LemonModal,
    LemonSnack,
    LemonSwitch,
    LemonTable,
    LemonTableColumns,
    LemonTag,
    Link,
} from '@posthog/lemon-ui'

import { NotFound } from 'lib/components/NotFound'
import { Sparkline } from 'lib/components/Sparkline'
import { TZLabel } from 'lib/components/TZLabel'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { LinkedHogFunctions } from 'scenes/hog-functions/list/LinkedHogFunctions'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneSection } from '~/layout/scenes/components/SceneSection'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'

import { ScenesTabs } from '../../components/ScenesTabs'
import type { TicketAlertRuleApi, TicketIncidentApi } from '../../generated/api.schemas'
import { supportTrendsLogic } from './supportTrendsLogic'

export const scene: SceneExport = {
    component: SupportTrendsScene,
    logic: supportTrendsLogic,
    productKey: ProductKey.CONVERSATIONS,
}

/** LemonInput number fields emit NaN when cleared; ?? only catches null/undefined. */
function finiteOr(value: number | undefined, fallback: number): number {
    return value != null && Number.isFinite(value) ? value : fallback
}

function windowLabel(windowMinutes: number | undefined): string {
    if (!windowMinutes) {
        return ''
    }
    if (windowMinutes === 60) {
        return '1 hour'
    }
    if (windowMinutes % 60 === 0) {
        return `${windowMinutes / 60} hours`
    }
    return `${windowMinutes} minutes`
}

function incidentTitle(incident: TicketIncidentApi): string {
    return (
        incident.details?.title ??
        `${incident.observed_count} tickets in the last ${windowLabel(incident.window_minutes)}`
    )
}

const INCIDENT_STATUS_TAG: Record<string, 'danger' | 'success' | 'muted'> = {
    active: 'danger',
    resolved: 'success',
    dismissed: 'muted',
}

function IncidentsTable({ incidents, loading }: { incidents: TicketIncidentApi[]; loading: boolean }): JSX.Element {
    const { dismissingIncidentIds } = useValues(supportTrendsLogic)
    const { dismissIncident } = useActions(supportTrendsLogic)

    const columns: LemonTableColumns<TicketIncidentApi> = [
        {
            title: 'Status',
            key: 'status',
            width: 0,
            render: (_, incident) => (
                <LemonTag type={INCIDENT_STATUS_TAG[incident.status ?? 'active'] ?? 'muted'}>
                    {incident.status}
                </LemonTag>
            ),
        },
        {
            title: 'Incident',
            key: 'title',
            render: (_, incident) => (
                <div className="flex flex-col">
                    <span className="font-medium">{incidentTitle(incident)}</span>
                    {incident.rule_name ? (
                        <span className="text-xs text-muted-alt">Rule: {incident.rule_name}</span>
                    ) : null}
                </div>
            ),
        },
        {
            title: 'Last 24h',
            key: 'sparkline',
            width: 160,
            render: (_, incident) => {
                const data = incident.details?.sparkline_hourly
                // Generated API arrays are readonly; Sparkline wants a mutable number[].
                return data && data.length > 0 ? <Sparkline data={[...data]} className="h-8 w-36" /> : null
            },
        },
        {
            title: 'Detected',
            key: 'detected_at',
            width: 130,
            render: (_, incident) => (incident.detected_at ? <TZLabel time={incident.detected_at} /> : null),
        },
        {
            key: 'actions',
            width: 0,
            render: (_, incident) => (
                <div className="flex gap-1">
                    <LemonButton size="xsmall" type="secondary" to={urls.supportTickets()}>
                        View tickets
                    </LemonButton>
                    {incident.status === 'active' ? (
                        <LemonButton
                            size="xsmall"
                            type="secondary"
                            loading={dismissingIncidentIds.includes(incident.id)}
                            onClick={() => dismissIncident(incident.id)}
                        >
                            Dismiss
                        </LemonButton>
                    ) : null}
                </div>
            ),
        },
    ]

    return (
        <LemonTable
            dataSource={incidents}
            columns={columns}
            loading={loading}
            rowKey="id"
            emptyState="No incidents detected. When ticket volume spikes abnormally or an alert rule triggers, it shows up here."
        />
    )
}

function ruleConditionLabel(rule: TicketAlertRuleApi): string {
    const base = `≥ ${rule.min_count} tickets in ${windowLabel(rule.window_minutes)}`
    return rule.spike_multiplier ? `${base} and ≥ ${rule.spike_multiplier}× normal` : base
}

function AlertRulesTable(): JSX.Element {
    const { alertRules, alertRulesLoading, mutatingRuleIds } = useValues(supportTrendsLogic)
    const { openEditRuleModal, deleteRule, toggleRuleEnabled } = useActions(supportTrendsLogic)

    const columns: LemonTableColumns<TicketAlertRuleApi> = [
        {
            title: 'Name',
            key: 'name',
            render: (_, rule) => (
                <div className="flex flex-col">
                    <span className="font-medium">{rule.name}</span>
                    <span className="text-xs text-muted-alt">{ruleConditionLabel(rule)}</span>
                </div>
            ),
        },
        {
            title: 'Filters',
            key: 'filters',
            render: (_, rule) => {
                const entries = Object.entries(rule.filters ?? {})
                if (entries.length === 0) {
                    return <span className="text-muted-alt">All tickets</span>
                }
                return (
                    <div className="flex flex-wrap gap-1">
                        {entries.map(([key, value]) => (
                            <LemonSnack key={key}>
                                {key}: {value}
                            </LemonSnack>
                        ))}
                    </div>
                )
            },
        },
        {
            title: 'Last fired',
            key: 'last_fired_at',
            width: 130,
            render: (_, rule) => (rule.last_fired_at ? <TZLabel time={rule.last_fired_at} /> : 'Never'),
        },
        {
            title: 'Enabled',
            key: 'enabled',
            width: 0,
            render: (_, rule) => (
                <LemonSwitch
                    checked={rule.enabled ?? true}
                    disabled={mutatingRuleIds.includes(rule.id)}
                    onChange={() => toggleRuleEnabled(rule)}
                />
            ),
        },
        {
            key: 'actions',
            width: 0,
            render: (_, rule) => (
                <div className="flex gap-1">
                    <LemonButton size="xsmall" type="secondary" onClick={() => openEditRuleModal(rule)}>
                        Edit
                    </LemonButton>
                    <LemonButton
                        size="xsmall"
                        status="danger"
                        type="secondary"
                        loading={mutatingRuleIds.includes(rule.id)}
                        onClick={() =>
                            LemonDialog.open({
                                title: `Delete alert rule "${rule.name}"?`,
                                description: 'Any active incident from this rule will resolve automatically.',
                                primaryButton: {
                                    children: 'Delete',
                                    status: 'danger',
                                    onClick: () => deleteRule(rule),
                                },
                                secondaryButton: { children: 'Cancel' },
                            })
                        }
                    >
                        Delete
                    </LemonButton>
                </div>
            ),
        },
    ]

    return (
        <LemonTable
            dataSource={alertRules}
            columns={columns}
            loading={alertRulesLoading}
            rowKey="id"
            emptyState={
                <>
                    No alert rules yet. Create one here to watch all tickets, or filter the{' '}
                    <Link to={urls.supportTickets()}>tickets list</Link> and use "Create alert rule" to watch a specific
                    slice.
                </>
            }
        />
    )
}

function RuleModal(): JSX.Element {
    const { ruleModalOpen, ruleDraft, ruleSaving } = useValues(supportTrendsLogic)
    const { closeRuleModal, setRuleDraft, saveRule } = useActions(supportTrendsLogic)

    const filterEntries = Object.entries(ruleDraft.filters)

    return (
        <LemonModal
            isOpen={ruleModalOpen}
            onClose={closeRuleModal}
            hasUnsavedInput={!!ruleDraft.name.trim() || Object.keys(ruleDraft.filters).length > 0}
            title={ruleDraft.id ? 'Edit alert rule' : 'New alert rule'}
            footer={
                <>
                    <LemonButton
                        type="secondary"
                        onClick={closeRuleModal}
                        disabledReason={ruleSaving ? 'Saving…' : undefined}
                    >
                        Cancel
                    </LemonButton>
                    <LemonButton type="primary" onClick={saveRule} loading={ruleSaving}>
                        {ruleDraft.id ? 'Save' : 'Create'}
                    </LemonButton>
                </>
            }
        >
            <div className="flex flex-col gap-4 max-w-160">
                <div>
                    <LemonLabel>Name</LemonLabel>
                    <LemonInput
                        autoFocus
                        placeholder="e.g. Billing complaints"
                        value={ruleDraft.name}
                        onChange={(name) => setRuleDraft({ name })}
                        onPressEnter={saveRule}
                    />
                </div>
                <div>
                    <LemonLabel>Filters</LemonLabel>
                    {filterEntries.length === 0 ? (
                        <p className="text-muted-alt text-xs mb-1">
                            No filters: the rule counts every new ticket. To watch a specific slice, filter the tickets
                            list and use "Create alert rule" there.
                        </p>
                    ) : (
                        <div className="flex flex-wrap gap-1 my-1">
                            {filterEntries.map(([key, value]) => (
                                <LemonSnack
                                    key={key}
                                    onClose={() => {
                                        const { [key]: _, ...rest } = ruleDraft.filters
                                        setRuleDraft({ filters: rest })
                                    }}
                                >
                                    {key}: {value}
                                </LemonSnack>
                            ))}
                        </div>
                    )}
                </div>
                <div className="flex gap-4">
                    <div>
                        <LemonLabel>Window (minutes)</LemonLabel>
                        <LemonInput
                            type="number"
                            min={15}
                            max={1440}
                            value={ruleDraft.window_minutes}
                            onChange={(value) => setRuleDraft({ window_minutes: finiteOr(value, 120) })}
                        />
                    </div>
                    <div>
                        <LemonLabel>Minimum tickets</LemonLabel>
                        <LemonInput
                            type="number"
                            min={1}
                            value={ruleDraft.min_count}
                            onChange={(value) => setRuleDraft({ min_count: finiteOr(value, 5) })}
                        />
                    </div>
                </div>
                <div>
                    <LemonSwitch
                        label="Also require a spike vs normal volume"
                        checked={ruleDraft.spike_multiplier != null}
                        onChange={(checked) => setRuleDraft({ spike_multiplier: checked ? 3 : null })}
                    />
                    {ruleDraft.spike_multiplier != null ? (
                        <div className="mt-2">
                            <LemonLabel>Spike multiplier</LemonLabel>
                            <LemonInput
                                type="number"
                                min={1.5}
                                max={100}
                                step={0.5}
                                value={ruleDraft.spike_multiplier}
                                onChange={(value) => setRuleDraft({ spike_multiplier: finiteOr(value, 3) })}
                            />
                            <p className="text-muted-alt text-xs mt-1">
                                The rule only fires when matching tickets also exceed this multiple of the usual volume
                                for the same time of day.
                            </p>
                        </div>
                    ) : null}
                </div>
            </div>
        </LemonModal>
    )
}

export function SupportTrendsScene(): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    const { activeIncidents, pastIncidents, incidentsLoading } = useValues(supportTrendsLogic)
    const { openNewRuleModal } = useActions(supportTrendsLogic)

    // The scene registry can't flag-gate routes, so gate here: hiding the tab alone
    // still leaves the URL reachable.
    if (!featureFlags[FEATURE_FLAGS.PRODUCT_SUPPORT_TICKET_TRENDS]) {
        return <NotFound object="page" />
    }

    return (
        <SceneContent className="pb-4">
            <SceneTitleSection
                name="Support"
                description=""
                resourceType={{
                    type: 'conversation',
                }}
            />
            <ScenesTabs />
            {activeIncidents.length > 0 ? (
                <LemonBanner type="warning">
                    {activeIncidents.length === 1
                        ? `Possible incident: ${incidentTitle(activeIncidents[0])}`
                        : `${activeIncidents.length} possible incidents are active`}
                </LemonBanner>
            ) : null}
            <SceneSection
                title="Incidents"
                titleSize="sm"
                description="Detected spikes in ticket volume: overall, per channel or priority, and from your alert rules. Incidents auto-resolve when volume returns to normal."
            >
                <IncidentsTable incidents={[...activeIncidents, ...pastIncidents]} loading={incidentsLoading} />
            </SceneSection>
            <SceneSection
                title="Alert rules"
                titleSize="sm"
                description="Set your own criteria for what counts as alert-worthy: any ticket filter plus a threshold, with an optional spike condition."
                actions={
                    <LemonButton type="primary" size="small" onClick={() => openNewRuleModal()}>
                        New alert rule
                    </LemonButton>
                }
            >
                <AlertRulesTable />
            </SceneSection>
            <SceneSection
                title="Notifications"
                titleSize="sm"
                description="Send detected incidents to Slack, Microsoft Teams, Discord, or a webhook."
            >
                <LinkedHogFunctions type="internal_destination" subTemplateIds={['conversations-incident-detected']} />
            </SceneSection>
            <RuleModal />
        </SceneContent>
    )
}
