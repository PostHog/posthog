import { useActions, useValues } from 'kea'
import { useState } from 'react'

import * as superheroPng from '@posthog/brand/hoggies/png/superhero'
import { IconArrowLeft, IconChevronRight, IconTrash } from '@posthog/icons'
import { LemonButton, LemonDivider, LemonSelect, LemonSwitch, LemonTag } from '@posthog/lemon-ui'

import { pngHoggie } from 'lib/brand/hoggies'
import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { preflightLogic } from 'lib/logic/preflightLogic'
import { maxGlobalLogic } from 'scenes/max/maxGlobalLogic'
import { organizationLogic } from 'scenes/organizationLogic'
import { teamLogic } from 'scenes/teamLogic'
import { userLogic } from 'scenes/userLogic'

import { customProductsLogic } from '~/layout/panel-layout/ProjectTree/customProductsLogic'
import { iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'
import { getTreeItemsProducts } from '~/products'
import type { TeamType } from '~/types'

import { openCHQueriesDebugModal } from '../Shortcuts/utils/DebugCHQueries'
import { FakeBillingAlert, FakeStatusOverride, superpowersLogic } from './superpowersLogic'

const HedgehogSuperhero = pngHoggie(superheroPng)

export function SuperpowersModal(): JSX.Element | null {
    const { isSuperpowersOpen } = useValues(superpowersLogic)
    const { closeSuperpowers } = useActions(superpowersLogic)

    return (
        <LemonModal title="" isOpen={isSuperpowersOpen} onClose={closeSuperpowers} width={760}>
            <SuperpowersContent />
        </LemonModal>
    )
}

const STATUS_OPTIONS: { value: FakeStatusOverride; label: string }[] = [
    { value: 'none', label: 'None (use real status)' },
    { value: 'operational', label: 'Operational' },
    { value: 'degraded_performance', label: 'Degraded performance' },
    { value: 'partial_outage', label: 'Partial outage' },
    { value: 'major_outage', label: 'Major outage' },
]

const BILLING_ALERT_OPTIONS: { value: FakeBillingAlert; label: string }[] = [
    { value: 'none', label: 'None (use real alerts)' },
    { value: 'info', label: 'Info' },
    { value: 'warning', label: 'Warning' },
    { value: 'error', label: 'Error' },
]

function Section({
    title,
    description,
    children,
}: {
    title: React.ReactNode
    description?: string
    children: React.ReactNode
}): JSX.Element {
    return (
        <div>
            <h3 className="font-semibold mb-0.5">{title}</h3>
            {description && <p className="text-xs text-secondary mb-2">{description}</p>}
            <div className="space-y-2">{children}</div>
        </div>
    )
}

function SettingRow({
    title,
    description,
    control,
}: {
    title: string
    description: string
    control: React.ReactNode
}): JSX.Element {
    return (
        <div className="flex items-center justify-between gap-4 p-2 border rounded">
            <div className="min-w-0">
                <div className="font-medium text-sm">{title}</div>
                <div className="text-xs text-secondary">{description}</div>
            </div>
            <div className="shrink-0">{control}</div>
        </div>
    )
}

interface CaptureOption {
    label: string
    /** The team field (or path) behind the option, shown for PATCHing/debugging. */
    field: string
    get: (team: TeamType) => boolean
}

// Capture settings behind each product's data, keyed by products-registry path.
const PRODUCT_CAPTURE_OPTIONS: Record<string, CaptureOption[]> = {
    'Product analytics': [
        { label: 'Autocapture', field: 'autocapture_opt_out', get: (t) => !t.autocapture_opt_out },
        { label: 'Heatmaps', field: 'heatmaps_opt_in', get: (t) => !!t.heatmaps_opt_in },
        { label: 'Dead clicks', field: 'capture_dead_clicks', get: (t) => !!t.capture_dead_clicks },
        { label: 'Web vitals', field: 'autocapture_web_vitals_opt_in', get: (t) => !!t.autocapture_web_vitals_opt_in },
    ],
    'Session replay': [
        { label: 'Recording', field: 'session_recording_opt_in', get: (t) => !!t.session_recording_opt_in },
        { label: 'Console logs', field: 'capture_console_log_opt_in', get: (t) => !!t.capture_console_log_opt_in },
        {
            label: 'Network performance',
            field: 'capture_performance_opt_in',
            get: (t) => !!t.capture_performance_opt_in,
        },
        {
            label: 'Canvas recording',
            field: 'session_replay_config.record_canvas',
            get: (t) => !!t.session_replay_config?.record_canvas,
        },
        {
            label: 'Network payloads',
            field: 'session_recording_network_payload_capture_config',
            get: (t) => !!t.session_recording_network_payload_capture_config,
        },
    ],
    'Error tracking': [
        {
            label: 'Exception autocapture',
            field: 'autocapture_exceptions_opt_in',
            get: (t) => !!t.autocapture_exceptions_opt_in,
        },
    ],
    'Web analytics': [
        { label: 'Web vitals', field: 'autocapture_web_vitals_opt_in', get: (t) => !!t.autocapture_web_vitals_opt_in },
        { label: 'Heatmaps', field: 'heatmaps_opt_in', get: (t) => !!t.heatmaps_opt_in },
        {
            label: 'Network performance',
            field: 'capture_performance_opt_in',
            get: (t) => !!t.capture_performance_opt_in,
        },
    ],
    Heatmaps: [
        { label: 'Heatmaps', field: 'heatmaps_opt_in', get: (t) => !!t.heatmaps_opt_in },
        { label: 'Dead clicks', field: 'capture_dead_clicks', get: (t) => !!t.capture_dead_clicks },
    ],
    Surveys: [{ label: 'Survey popups', field: 'surveys_opt_in', get: (t) => !!t.surveys_opt_in }],
    Logs: [
        {
            label: 'Console log capture',
            field: 'logs_settings.capture_console_logs',
            get: (t) => !!(t.logs_settings as Record<string, any> | null)?.capture_console_logs,
        },
    ],
    Support: [
        { label: 'Conversations', field: 'conversations_enabled', get: (t) => !!t.conversations_enabled },
        {
            label: 'Widget',
            field: 'conversations_settings.widget_enabled',
            get: (t) => !!(t.conversations_settings as Record<string, any> | null)?.widget_enabled,
        },
    ],
}

function CaptureOptionDot({ option, team }: { option: CaptureOption; team: TeamType }): JSX.Element {
    const on = option.get(team)
    return (
        <span className="flex items-baseline gap-1.5 text-xs whitespace-nowrap min-w-0">
            <span className={`size-1.5 shrink-0 rounded-full self-center ${on ? 'bg-success' : 'bg-danger'}`} />
            <span>{option.label}</span>
            <code className="text-[10px] text-muted truncate">{option.field}</code>
        </span>
    )
}

function EnablementTag({ enabled }: { enabled: boolean }): JSX.Element {
    return enabled ? (
        <LemonTag type="success" className="shrink-0">
            Enabled
        </LemonTag>
    ) : (
        <LemonTag className="shrink-0">Disabled</LemonTag>
    )
}

function ProductsSection(): JSX.Element {
    const { customProducts, customProductsLoading } = useValues(customProductsLogic)
    const { loadCustomProducts } = useActions(customProductsLogic)
    const { currentTeam } = useValues(teamLogic)

    // The modal content unmounts on close, so each open refetches the sidebar list.
    useOnMountEffect(() => loadCustomProducts())

    const team = currentTeam as TeamType | null
    const enabledByPath = new Map(customProducts.map((item) => [item.product_path, item]))
    const products = getTreeItemsProducts()
    const withOptions = products.filter((item) => PRODUCT_CAPTURE_OPTIONS[item.path])
    const others = products.filter((item) => !PRODUCT_CAPTURE_OPTIONS[item.path])
    const enabledCount = products.filter((item) => enabledByPath.has(item.path)).length

    return (
        <Section
            title={
                <>
                    Products{' '}
                    <span className="font-normal text-secondary text-sm">
                        ({enabledCount} of {products.length} in sidebar)
                    </span>
                </>
            }
            description="Sidebar enablement per product (UserProductList), plus the team capture settings behind each tool. A red dot means the tool renders but captures nothing."
        >
            <div className="space-y-2">
                <div className="space-y-1.5">
                    {withOptions.map((item) => {
                        const listItem = enabledByPath.get(item.path)
                        return (
                            <div key={item.path} className="border rounded p-2.5 space-y-1.5">
                                <div className="flex items-center gap-2">
                                    <span className="flex shrink-0 group/colorful-product-icons colorful-product-icons-true">
                                        {iconForType(item.iconType)}
                                    </span>
                                    <span className="flex-1 text-sm font-medium truncate">{item.path}</span>
                                    <EnablementTag enabled={!!listItem} />
                                </div>
                                {team && (
                                    <div className="grid grid-cols-2 gap-x-4 gap-y-1 pl-6">
                                        {PRODUCT_CAPTURE_OPTIONS[item.path].map((option) => (
                                            <CaptureOptionDot key={option.field} option={option} team={team} />
                                        ))}
                                    </div>
                                )}
                            </div>
                        )
                    })}
                </div>
                {others.length > 0 && (
                    <>
                        <div className="text-xs text-muted font-medium pt-1">No capture settings</div>
                        <div className="grid grid-cols-2 gap-1">
                            {others.map((item) => (
                                <div key={item.path} className="flex items-center gap-2 border rounded px-2 py-1">
                                    <span className="flex shrink-0 group/colorful-product-icons colorful-product-icons-true">
                                        {iconForType(item.iconType)}
                                    </span>
                                    <span className="flex-1 text-xs truncate">{item.path}</span>
                                    <EnablementTag enabled={enabledByPath.has(item.path)} />
                                </div>
                            ))}
                        </div>
                    </>
                )}
            </div>
            {customProductsLoading && <div className="text-xs text-secondary">Refreshing…</div>}
        </Section>
    )
}

function SuperpowersContent(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const { updateCurrentTeam } = useActions(teamLogic)
    const { user } = useValues(userLogic)
    const { fakeStatusOverride, fakeBillingAlert, mcpHintsDismissed } = useValues(superpowersLogic)
    const { closeSuperpowers, setFakeStatusOverride, setFakeBillingAlert, reenableMCPHints } =
        useActions(superpowersLogic)
    const { dataProcessingAccepted } = useValues(maxGlobalLogic)
    const { updateOrganization } = useActions(organizationLogic)
    const { isDev } = useValues(preflightLogic)

    const clearOnboardingTasks = (): void => {
        updateCurrentTeam({ onboarding_tasks: {} })
    }

    const handleOpenCHQueries = (): void => {
        closeSuperpowers()
        openCHQueriesDebugModal()
    }

    const [view, setView] = useState<'home' | 'tools'>('home')

    if (view === 'tools') {
        return (
            <div className="space-y-4">
                <div className="flex items-center gap-2 -mt-2">
                    <LemonButton
                        icon={<IconArrowLeft />}
                        size="small"
                        onClick={() => setView('home')}
                        aria-label="Back"
                    />
                    <h2 className="text-xl font-bold m-0">Tool status</h2>
                </div>
                <ProductsSection />
            </div>
        )
    }

    return (
        <div className="space-y-5">
            {/* Hero section */}
            <div className="flex items-center gap-4 -mt-2">
                <HedgehogSuperhero className="w-20 h-20 shrink-0" />
                <div>
                    <h2 className="text-xl font-bold mb-1">Super Hog Powers</h2>
                    <p className="text-secondary text-sm m-0">
                        With great power comes great responsibility. Use these wisely, fellow hog.
                    </p>
                </div>
            </div>

            <LemonDivider />

            <Section title="Actions">
                <SettingRow
                    title="Tool status"
                    description="Every product's sidebar enablement and the team capture settings behind it"
                    control={
                        <LemonButton
                            type="secondary"
                            size="small"
                            sideIcon={<IconChevronRight />}
                            onClick={() => setView('tools')}
                        >
                            Open
                        </LemonButton>
                    }
                />
            </Section>

            <LemonDivider />

            <Section title="Quick start / Onboarding">
                <SettingRow
                    title="Clear all onboarding tasks"
                    description="Reset all quick start task progress for this team"
                    control={
                        <LemonButton
                            type="secondary"
                            status="danger"
                            icon={<IconTrash />}
                            size="small"
                            onClick={clearOnboardingTasks}
                        >
                            Clear
                        </LemonButton>
                    }
                />
                <div className="text-xs text-secondary font-mono p-2 bg-surface-tertiary rounded max-h-40 overflow-auto whitespace-pre">
                    Current tasks: {JSON.stringify(currentTeam?.onboarding_tasks || {}, null, 2)}
                </div>
            </Section>

            <LemonDivider />

            <Section title="Simulations" description="Fake states for testing surfaces that are hard to reproduce.">
                <SettingRow
                    title="Fake status override"
                    description="Simulate a status outage for testing the status indicator"
                    control={
                        <LemonSelect
                            size="small"
                            value={fakeStatusOverride}
                            options={STATUS_OPTIONS}
                            onChange={setFakeStatusOverride}
                        />
                    }
                />
                <SettingRow
                    title="Fake billing alert"
                    description="Simulate a billing alert banner for testing"
                    control={
                        <LemonSelect
                            size="small"
                            value={fakeBillingAlert}
                            options={BILLING_ALERT_OPTIONS}
                            onChange={setFakeBillingAlert}
                        />
                    }
                />
            </Section>

            <LemonDivider />

            <Section title="Debug tools">
                <SettingRow
                    title="ClickHouse queries"
                    description="View recent ClickHouse queries for this user"
                    control={
                        <LemonButton type="secondary" size="small" onClick={handleOpenCHQueries}>
                            Open
                        </LemonButton>
                    }
                />
                <SettingRow
                    title="Re-enable MCP hints"
                    description="Clear all dismissed surfaces, the global opt-out, and the cooldown so hints show again"
                    control={
                        <LemonButton
                            type="secondary"
                            size="small"
                            onClick={reenableMCPHints}
                            disabledReason={mcpHintsDismissed ? undefined : 'No MCP hints are currently dismissed'}
                        >
                            Re-enable
                        </LemonButton>
                    }
                />
                {isDev && (
                    <SettingRow
                        title="Enable AI data processing"
                        description="Toggle organization-level AI data processing approval (dev only)"
                        control={
                            <LemonSwitch
                                checked={dataProcessingAccepted}
                                onChange={(checked) => updateOrganization({ is_ai_data_processing_approved: checked })}
                            />
                        }
                    />
                )}
            </Section>

            <LemonDivider />

            <div className="text-xs text-secondary">
                <div>
                    User: {user?.email} {user?.is_staff ? '(staff)' : ''}{' '}
                    {user?.is_impersonated ? '(impersonated)' : ''}
                </div>
                <div>Team ID: {currentTeam?.id}</div>
            </div>
        </div>
    )
}
