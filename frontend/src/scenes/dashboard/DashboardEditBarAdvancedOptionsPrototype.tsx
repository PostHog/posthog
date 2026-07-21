/**
 * PROTOTYPE — throwaway, do not ship. Dev builds only.
 *
 * Question: how should a "…" advanced-options affordance at the end of the dashboard
 * edit bar look, hosting a tri-state test account filter override
 * (inherit per insight / force filtering on / force filtering off)?
 *
 * Three structurally different variants on the existing dashboard route, switchable via
 * `?variant=` (A/B/C) and the floating PrototypeSwitcher bar:
 *   A — "…" opens a compact dropdown menu with radio-style choices
 *   B — "…" opens an "Advanced filters" panel (labelled control, explanation, room to grow)
 *   C — "…" expands the edit bar inline with a "test accounts" select, echoing "grouped by"
 *
 * The override lives in useState only — nothing is persisted or sent to the backend.
 * DashboardFilter already has the matching schema field (`filterTestAccounts`), unused so far.
 * A production version should use quill DropdownMenu for the menu variant per conventions.
 */
import { useValues } from 'kea'
import { router } from 'kea-router'
import { useState } from 'react'

import { IconCheck, IconEllipsis, IconGear, IconX } from '@posthog/icons'
import {
    LemonBadge,
    LemonButton,
    LemonDivider,
    LemonLabel,
    LemonSegmentedButton,
    LemonSelect,
    LemonSnack,
} from '@posthog/lemon-ui'

import { PrototypeSwitcher, PrototypeVariant } from 'lib/components/PrototypeSwitcher'
import { Popover } from 'lib/lemon-ui/Popover'
import { urls } from 'scenes/urls'

type TestAccountOverride = 'inherit' | 'filter-out' | 'include'

interface VariantProps {
    value: TestAccountOverride
    onChange: (value: TestAccountOverride) => void
}

const VARIANTS: PrototypeVariant[] = [
    { key: 'A', name: 'Dropdown menu' },
    { key: 'B', name: 'Advanced filters panel' },
    { key: 'C', name: 'Inline expansion' },
]

const STATE_SUMMARY: Record<TestAccountOverride, string> = {
    inherit: "each insight's own setting",
    'filter-out': 'filtered out everywhere',
    include: 'included everywhere',
}

export function DashboardEditBarAdvancedOptionsPrototype(): JSX.Element | null {
    if (process.env.NODE_ENV !== 'development') {
        return null
    }
    return <PrototypeHost />
}

function PrototypeHost(): JSX.Element {
    const { searchParams } = useValues(router)
    const variant = VARIANTS.some((v) => v.key === searchParams.variant) ? searchParams.variant : 'A'
    const [override, setOverride] = useState<TestAccountOverride>('inherit')

    return (
        <>
            {variant === 'A' && <VariantMenu value={override} onChange={setOverride} />}
            {variant === 'B' && <VariantPanel value={override} onChange={setOverride} />}
            {variant === 'C' && <VariantInline value={override} onChange={setOverride} />}
            <PrototypeSwitcher
                variants={VARIANTS}
                current={variant}
                stateLabel={`test accounts: ${STATE_SUMMARY[override]}`}
            />
        </>
    )
}

// --- Variant A: "…" opens a compact menu with radio-style choices ---------------------------

const MENU_OPTIONS: { value: TestAccountOverride; label: string; description: string }[] = [
    { value: 'inherit', label: 'Inherit from each insight', description: 'Insights keep their own setting' },
    { value: 'filter-out', label: 'Filter out test accounts', description: 'Force filtering on for every insight' },
    { value: 'include', label: 'Include test accounts', description: 'Force filtering off for every insight' },
]

function VariantMenu({ value, onChange }: VariantProps): JSX.Element {
    const [visible, setVisible] = useState(false)

    return (
        <Popover
            visible={visible}
            onClickOutside={() => setVisible(false)}
            placement="bottom-start"
            overlay={
                <div className="flex w-72 flex-col gap-0.5 p-1">
                    <div className="px-2 pb-0.5 pt-1 text-xs font-semibold uppercase text-secondary">
                        Test account filtering
                    </div>
                    {MENU_OPTIONS.map((option) => (
                        <LemonButton
                            key={option.value}
                            fullWidth
                            size="small"
                            active={value === option.value}
                            icon={value === option.value ? <IconCheck /> : <span className="w-4" />}
                            onClick={() => {
                                onChange(option.value)
                                setVisible(false)
                            }}
                        >
                            <div className="flex flex-col py-0.5">
                                <span>{option.label}</span>
                                <span className="text-xs text-secondary">{option.description}</span>
                            </div>
                        </LemonButton>
                    ))}
                </div>
            }
        >
            <span className="relative">
                <LemonButton
                    size="small"
                    icon={<IconEllipsis />}
                    tooltip="Advanced options"
                    active={visible}
                    onClick={() => setVisible(!visible)}
                />
                <LemonBadge size="small" position="top-right" visible={value !== 'inherit'} />
            </span>
        </Popover>
    )
}

// --- Variant B: "…" opens an "Advanced filters" panel ---------------------------------------

const PANEL_HINTS: Record<TestAccountOverride, string> = {
    inherit: 'Each insight uses its own "filter out internal and test users" setting.',
    'filter-out': 'Internal and test users are filtered out of every insight on this dashboard.',
    include: 'Internal and test users are included in every insight on this dashboard.',
}

function VariantPanel({ value, onChange }: VariantProps): JSX.Element {
    const [visible, setVisible] = useState(false)
    const overrideCount = value !== 'inherit' ? 1 : 0

    return (
        <Popover
            visible={visible}
            onClickOutside={() => setVisible(false)}
            placement="bottom-end"
            overlay={
                <div className="flex w-80 flex-col gap-2 p-2">
                    <div>
                        <h4 className="mb-0 font-semibold">Advanced filters</h4>
                        <p className="mb-0 text-xs text-secondary">
                            Overrides applied to every insight on this dashboard.
                        </p>
                    </div>
                    <LemonDivider className="my-0" />
                    <div className="flex items-center justify-between gap-2">
                        <LemonLabel info="Force test account filtering on or off for all insights, or let each insight keep its own setting.">
                            Test account filtering
                        </LemonLabel>
                        <LemonButton
                            icon={<IconGear />}
                            size="xsmall"
                            noPadding
                            to={urls.settings('project-product-analytics', 'internal-user-filtering')}
                            tooltip="Configure internal and test account filters"
                        />
                    </div>
                    <LemonSegmentedButton<TestAccountOverride>
                        fullWidth
                        size="small"
                        value={value}
                        onChange={(next) => onChange(next)}
                        options={[
                            { value: 'inherit', label: 'Inherit' },
                            { value: 'filter-out', label: 'Filter out' },
                            { value: 'include', label: 'Include' },
                        ]}
                    />
                    <p className="mb-0 text-xs text-secondary">{PANEL_HINTS[value]}</p>
                </div>
            }
        >
            <LemonButton
                size="small"
                type={overrideCount ? 'secondary' : 'tertiary'}
                icon={<IconEllipsis />}
                tooltip="Advanced filters"
                active={visible}
                onClick={() => setVisible(!visible)}
                sideIcon={overrideCount ? <LemonBadge.Number count={overrideCount} size="small" /> : undefined}
            />
        </Popover>
    )
}

// --- Variant C: "…" expands the bar inline, echoing the "grouped by" idiom ------------------

function VariantInline({ value, onChange }: VariantProps): JSX.Element {
    const [expanded, setExpanded] = useState(false)

    if (!expanded) {
        return (
            <span className="flex items-center gap-2">
                {value !== 'inherit' && (
                    <LemonSnack onClose={() => onChange('inherit')} title="Remove override">
                        test accounts {value === 'filter-out' ? 'filtered out' : 'included'}
                    </LemonSnack>
                )}
                <LemonButton
                    size="small"
                    icon={<IconEllipsis />}
                    tooltip="More filters"
                    onClick={() => setExpanded(true)}
                />
            </span>
        )
    }

    return (
        <span className="flex items-center gap-2">
            <span className="hidden md:inline">test accounts</span>
            <LemonSelect<TestAccountOverride>
                size="small"
                value={value}
                dropdownMatchSelectWidth={false}
                onChange={(next) => onChange(next)}
                options={[
                    { value: 'inherit', label: "each insight's setting" },
                    { value: 'filter-out', label: 'filtered out' },
                    { value: 'include', label: 'included' },
                ]}
            />
            <LemonButton
                size="small"
                icon={<IconX />}
                tooltip="Hide advanced filters"
                onClick={() => setExpanded(false)}
            />
        </span>
    )
}
