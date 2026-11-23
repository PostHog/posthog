import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconCheck, IconPlus, IconTrash, IconX } from '@posthog/icons'
import {
    LemonButton,
    LemonCard,
    LemonColorGlyph,
    LemonDivider,
    LemonSegmentedButton,
    Link,
    LemonSwitch,
    LemonTable,
    LemonTableColumns,
    LemonTag,
    Tooltip,
} from '@posthog/lemon-ui'
import {
    Badge,
    Button,
    Card,
    CardContent,
    Empty,
    EmptyHeader,
    EmptyTitle,
    Heading,
    Separator,
    Skeleton,
    Table,
    TableBody,
    TableCell,
    TableEmpty,
    TableHead,
    TableHeader,
    TableRow,
    Text,
    ToggleGroup,
    ToggleGroupItem,
    Tooltip as QuillTooltip,
    TooltipContent,
    TooltipTrigger,
} from '@posthog/quill'

import type { DataColorToken } from 'lib/colors'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { TZLabel } from 'lib/components/TZLabel'
import { TeamMembershipLevel } from 'lib/constants'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { humanFriendlyDiff } from 'lib/utils/durations'
import { QuillSettingSwitch } from 'scenes/settings/components/QuillSettingSwitch'

import type { AccountsTableCustomPropertyDefinition } from '~/queries/schema/schema-general'
import { PropertyFilterType, PropertyOperator, type AnyPropertyFilter } from '~/types'

import { AccountNameCell } from 'products/customer_analytics/frontend/components/Accounts/AccountNameCell'
import { accountsColumnConfigLogic } from 'products/customer_analytics/frontend/components/Accounts/accountsColumnConfigLogic'
import {
    ACCOUNT_FIELD_TAXONOMIC_OPTIONS,
    ACCOUNT_FILTER_OPERATOR_ALLOWLIST,
    accountFilterStaticValueOptions,
    type AccountFilter,
    isAccountPropertyFilter,
} from 'products/customer_analytics/frontend/components/Accounts/accountsPropertyFilters'
import { QuillOptionColorSwatch } from 'products/customer_analytics/frontend/components/QuillOptionColorSwatch'
import type {
    AccountTrackRuleConditionApi,
    AccountTrackRuleGroupApi,
    AccountTrackRuleRunViewApi,
    AccountTrackRuleSampleApi,
} from 'products/customer_analytics/frontend/generated/api.schemas'

import { accountTrackRulesLogic, type accountTrackRulesLogicValues } from './accountTrackRulesLogic'
import { formatCustomPropertyValue } from './customPropertyTypes'

const TRACK_RULE_ACCOUNT_FIELDS = ACCOUNT_FIELD_TAXONOMIC_OPTIONS.filter(
    ({ id }) => id !== 'ignored_at' && id !== 'churned_at'
)
const ACCOUNT_FIELD_LABELS = Object.fromEntries(ACCOUNT_FIELD_TAXONOMIC_OPTIONS.map(({ id, name }) => [id, name]))
const TERMINAL_RUN_STATUSES = new Set(['completed', 'failed', 'stale'])
const PREVIEW_SAMPLE_OPTIONS: { value: PreviewSampleKind; label: string }[] = [
    { value: 'included', label: 'Included' },
    { value: 'excluded', label: 'Excluded' },
]

export function getTrackRuleRunTriggerLabel(trigger: string): string {
    if (trigger === 'manual') {
        return 'Manual'
    }
    if (trigger === 'scheduled') {
        return 'Scheduled'
    }
    return trigger
}

export function getTrackRuleRunDuration(run: AccountTrackRuleRunViewApi): string {
    if (!run.started_at) {
        return 'Not started'
    }
    if (!run.finished_at) {
        return 'In progress'
    }
    return humanFriendlyDiff(run.started_at, run.finished_at)
}

function primitiveValues(value: AccountFilter['value']): (string | number | boolean)[] {
    const values = Array.isArray(value) ? value : value == null ? [] : [value]
    return values.filter(
        (item): item is string | number | boolean =>
            typeof item === 'string' || typeof item === 'number' || typeof item === 'boolean'
    )
}

export function accountFiltersToRuleGroup(filters: AccountFilter[]): AccountTrackRuleGroupApi {
    return {
        conditions: filters.map(
            (filter): AccountTrackRuleConditionApi => ({
                field: isAccountPropertyFilter(filter)
                    ? { kind: 'account_field', field: filter.key as AccountTrackRuleConditionApi['field']['field'] }
                    : { kind: 'custom_property', definition_id: filter.key },
                operator: filter.operator,
                values: primitiveValues(filter.value),
            })
        ),
    }
}

export function ruleGroupToAccountFilters(
    group: AccountTrackRuleGroupApi,
    definitionsById: Record<string, AccountsTableCustomPropertyDefinition>
): AccountFilter[] {
    return group.conditions.map((condition) => {
        const isNative = condition.field.kind === 'account_field'
        const key = isNative ? (condition.field.field ?? '') : (condition.field.definition_id ?? '')
        return {
            key,
            value: condition.values ?? [],
            operator: condition.operator as PropertyOperator,
            type: isNative ? PropertyFilterType.Account : PropertyFilterType.AccountCustomProperty,
            label: isNative ? undefined : definitionsById[key]?.name,
        } as AccountFilter
    })
}

export function AccountTrackRules(): JSX.Element {
    const {
        config,
        configLoading,
        draft,
        hasUnsavedChanges,
        canSave,
        canPreview,
        saveResponseLoading,
        previewResponse,
        previewResponseLoading,
        previewedDraft,
        previewMatchesDraft,
        runs,
        runsLoading,
        canRun,
        currentRunLoading,
    } = useValues(accountTrackRulesLogic)
    const { toggleEnabled, addGroup, updateGroup, removeGroup, saveConfig, previewDraft, startRun, loadRuns } =
        useActions(accountTrackRulesLogic)
    const { customPropertyTaxonomicOptions, customPropertyDefinitionsById, customPropertyDefinitionsLoading } =
        useValues(accountsColumnConfigLogic)
    const restrictionReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })
    const trackRulePropertyDefinitions = [...TRACK_RULE_ACCOUNT_FIELDS, ...customPropertyTaxonomicOptions].map(
        ({ id, property_type }) => ({ id, name: id, property_type })
    )
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    const confirmRun = (): void => {
        if (!config?.enabled || hasUnsavedChanges || !canRun) {
            return
        }
        LemonDialog.open({
            title: 'Apply these track rules?',
            description: 'This applies the saved rules to active accounts. Churned accounts will not change.',
            primaryButton: {
                children: 'Run now',
                onClick: startRun,
            },
            secondaryButton: { children: 'Cancel' },
        })
    }

    if ((configLoading && !config) || customPropertyDefinitionsLoading) {
        return todayRailNav ? (
            <div className="flex max-w-240 flex-col gap-2">
                <Skeleton className="h-8 w-full" />
                <Skeleton className="h-24 w-full" />
            </div>
        ) : (
            <div className="text-secondary">Loading track rules…</div>
        )
    }

    const enabledDisabledReason =
        restrictionReason ||
        (saveResponseLoading
            ? 'Saving track rules'
            : hasUnsavedChanges
              ? 'Save changes before enabling or disabling track rules'
              : !canPreview
                ? 'Add and save at least one group before enabling track rules'
                : undefined)
    const addGroupDisabledReason =
        restrictionReason || (draft.groups.length >= 20 ? 'A rule can have up to 20 groups' : undefined)
    const saveDisabledReason =
        restrictionReason ||
        (!hasUnsavedChanges ? 'No changes to save' : !canSave ? 'Add at least one condition to every group' : undefined)
    const previewDisabledReason =
        restrictionReason || (!canPreview ? 'Add at least one condition to every group' : undefined)
    const runDisabledReason =
        restrictionReason ||
        (hasUnsavedChanges
            ? 'Save changes before running track rules'
            : !config?.enabled
              ? 'Enable track rules before running them'
              : !canRun
                ? 'Another run is in progress'
                : undefined)

    const renderGroupFilters = (group: AccountTrackRuleGroupApi, index: number): JSX.Element => (
        <PropertyFilters
            propertyFilters={
                ruleGroupToAccountFilters(group, customPropertyDefinitionsById) as unknown as AnyPropertyFilter[]
            }
            onChange={(filters) => updateGroup(index, accountFiltersToRuleGroup(filters as unknown as AccountFilter[]))}
            pageKey={`customer-analytics-account-track-rules-${index}`}
            taxonomicGroupTypes={[
                TaxonomicFilterGroupType.AccountFields,
                TaxonomicFilterGroupType.AccountCustomProperties,
            ]}
            taxonomicFilterOptionsFromProp={{
                [TaxonomicFilterGroupType.AccountFields]: TRACK_RULE_ACCOUNT_FIELDS,
                [TaxonomicFilterGroupType.AccountCustomProperties]: customPropertyTaxonomicOptions,
            }}
            operatorAllowlist={ACCOUNT_FILTER_OPERATOR_ALLOWLIST}
            propertyDefinitionsOverride={trackRulePropertyDefinitions}
            allowRelativeDateOptions
            staticValueOptions={accountFilterStaticValueOptions}
            editable={!restrictionReason}
            disabledReason={restrictionReason ?? undefined}
            hasRowOperator={false}
        />
    )

    const previewResult = previewResponse && (
        <PreviewResult
            preview={previewResponse}
            current={previewMatchesDraft}
            ruleGroups={previewedDraft?.groups ?? []}
            definitionsById={customPropertyDefinitionsById}
        />
    )

    if (todayRailNav) {
        return (
            <div className="flex max-w-240 flex-col gap-4" data-attr="account-track-rules">
                <div className="flex flex-wrap items-start justify-between gap-4">
                    <Text size="xs" variant="muted" render={<p className="m-0 max-w-160" />}>
                        Accounts matching any group stay tracked. Conditions inside a group must all match. Previewing
                        does not save changes. Turning rules on saves and applies them immediately. Turning rules off
                        stops future runs and does not restore accounts.
                    </Text>
                    <QuillSettingSwitch
                        label="Enabled"
                        checked={draft.enabled}
                        onCheckedChange={toggleEnabled}
                        disabledReason={enabledDisabledReason}
                    />
                </div>

                {draft.groups.map((group, index) => (
                    <Card key={index} size="sm">
                        <CardContent className="flex flex-col gap-3">
                            <div className="flex items-center justify-between gap-2">
                                <span className="flex items-center gap-2">
                                    <Text size="sm" render={<span className="m-0 font-semibold" />}>
                                        Group {index + 1}
                                    </Text>
                                    {index > 0 && (
                                        <Text size="xs" variant="muted" render={<span className="m-0" />}>
                                            OR
                                        </Text>
                                    )}
                                </span>
                                <Button
                                    variant="destructive-outline"
                                    size="icon"
                                    aria-label="Remove group"
                                    tooltip="Remove group"
                                    onClick={() => removeGroup(index)}
                                    disabledReason={restrictionReason}
                                >
                                    <IconTrash />
                                </Button>
                            </div>
                            {renderGroupFilters(group, index)}
                            <Text size="xs" variant="muted" render={<span className="m-0" />}>
                                All conditions in this group use AND.
                            </Text>
                        </CardContent>
                    </Card>
                ))}

                <div>
                    <Button variant="outline" onClick={addGroup} disabledReason={addGroupDisabledReason}>
                        <IconPlus />
                        Add OR group
                    </Button>
                </div>

                <div className="flex flex-wrap gap-2">
                    <Button
                        variant="primary"
                        onClick={saveConfig}
                        loading={saveResponseLoading}
                        disabledReason={saveDisabledReason}
                    >
                        Save
                    </Button>
                    <Button
                        variant="outline"
                        onClick={previewDraft}
                        loading={previewResponseLoading}
                        disabledReason={previewDisabledReason}
                    >
                        Preview
                    </Button>
                    <Button
                        variant="outline"
                        onClick={confirmRun}
                        loading={currentRunLoading}
                        disabledReason={runDisabledReason}
                    >
                        Run now
                    </Button>
                </div>

                {previewResult}

                <Separator />
                <div className="flex flex-wrap items-center justify-between gap-2">
                    <Heading size="sm" render={<h3 className="m-0" />}>
                        Recent runs
                    </Heading>
                    <Button variant="outline" onClick={loadRuns} loading={runsLoading}>
                        Refresh
                    </Button>
                </div>
                <RunHistory runs={runs} loading={runsLoading} />
            </div>
        )
    }

    return (
        <div className="flex flex-col gap-4 max-w-240" data-attr="account-track-rules">
            <div className="flex items-start justify-between gap-4">
                <div>
                    <h2 className="text-lg font-semibold mb-1">Account track rules</h2>
                    <p className="text-secondary mb-0">
                        Accounts matching any group stay tracked. Conditions inside a group must all match. Previewing
                        does not save changes. Turning rules on saves and applies them immediately. Turning rules off
                        stops future runs and does not restore accounts.
                    </p>
                </div>
                <LemonSwitch
                    checked={draft.enabled}
                    onChange={toggleEnabled}
                    label="Enabled"
                    disabledReason={enabledDisabledReason}
                />
            </div>

            {draft.groups.map((group, index) => (
                <LemonCard key={index} hoverEffect={false} className="p-4 flex flex-col gap-3">
                    <div className="flex items-center justify-between">
                        <div>
                            <span className="font-semibold">Group {index + 1}</span>
                            {index > 0 && <span className="text-secondary ml-2">OR</span>}
                        </div>
                        <LemonButton
                            size="small"
                            icon={<IconTrash />}
                            status="danger"
                            onClick={() => removeGroup(index)}
                            disabledReason={restrictionReason}
                            tooltip="Remove group"
                        />
                    </div>
                    {renderGroupFilters(group, index)}
                    <span className="text-xs text-secondary">All conditions in this group use AND.</span>
                </LemonCard>
            ))}

            <div>
                <LemonButton
                    type="secondary"
                    icon={<IconPlus />}
                    onClick={addGroup}
                    disabledReason={addGroupDisabledReason}
                >
                    Add OR group
                </LemonButton>
            </div>

            <div className="flex flex-wrap gap-2">
                <LemonButton
                    type="primary"
                    onClick={saveConfig}
                    loading={saveResponseLoading}
                    disabledReason={saveDisabledReason}
                >
                    Save
                </LemonButton>
                <LemonButton
                    type="secondary"
                    onClick={previewDraft}
                    loading={previewResponseLoading}
                    disabledReason={previewDisabledReason}
                >
                    Preview
                </LemonButton>
                <LemonButton
                    type="secondary"
                    onClick={confirmRun}
                    loading={currentRunLoading}
                    disabledReason={runDisabledReason}
                >
                    Run now
                </LemonButton>
            </div>

            {previewResult}

            <LemonDivider />
            <div className="flex items-center justify-between">
                <h3 className="text-base font-semibold mb-0">Recent runs</h3>
                <LemonButton type="secondary" size="small" onClick={loadRuns} loading={runsLoading}>
                    Refresh
                </LemonButton>
            </div>
            <RunHistory runs={runs} loading={runsLoading} />
        </div>
    )
}

type PreviewMetric = {
    key: 'eligible_active' | 'skipped_churned' | 'tracked' | 'ignored'
    deltaKey?: 'restored' | 'newly_ignored'
    label: string
    tooltip: string
}

const PREVIEW_METRICS = [
    {
        key: 'eligible_active',
        label: 'Eligible active',
        tooltip: 'Active accounts evaluated by this preview. Churned accounts are not eligible.',
    },
    {
        key: 'skipped_churned',
        label: 'Churned skipped',
        tooltip: 'Churned accounts excluded from evaluation. Applying these rules will not change them.',
    },
    {
        key: 'tracked',
        deltaKey: 'restored',
        label: 'Tracked',
        tooltip:
            'Eligible accounts that match at least one group. The number in parentheses shows ignored accounts that will be restored.',
    },
    {
        key: 'ignored',
        deltaKey: 'newly_ignored',
        label: 'Ignored',
        tooltip:
            'Eligible accounts that do not match any group. The number in parentheses shows tracked accounts that will become ignored.',
    },
] satisfies PreviewMetric[]

type PreviewSampleKind = 'included' | 'excluded'

type PreviewRuleColumn = {
    key: string
    label: string
    definition?: AccountsTableCustomPropertyDefinition
}

export function getPreviewRuleColumns(
    groups: readonly AccountTrackRuleGroupApi[],
    definitionsById: Record<string, AccountsTableCustomPropertyDefinition>
): PreviewRuleColumn[] {
    const columns: PreviewRuleColumn[] = []
    const keys = new Set<string>()
    for (const group of groups) {
        for (const condition of group.conditions) {
            if (condition.field.kind === 'account_field') {
                const field = condition.field.field
                if (!field || field === 'name' || field === 'external_id') {
                    continue
                }
                const key = `account_field:${field}`
                if (!keys.has(key)) {
                    keys.add(key)
                    columns.push({ key, label: ACCOUNT_FIELD_LABELS[field] ?? field })
                }
            } else {
                const definitionId = condition.field.definition_id
                if (!definitionId) {
                    continue
                }
                const key = `custom_property:${definitionId}`
                if (!keys.has(key)) {
                    keys.add(key)
                    const definition = definitionsById[definitionId]
                    columns.push({ key, label: definition?.name ?? definitionId, definition })
                }
            }
        }
    }
    return columns
}

function PreviewRuleValue({
    value,
    definition,
}: {
    value: unknown
    definition?: AccountsTableCustomPropertyDefinition
}): JSX.Element {
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    if (value === null || value === undefined || value === '') {
        return <span className="text-muted">—</span>
    }
    const stringValue = String(value)
    if (definition?.display_type === 'date' || definition?.display_type === 'datetime') {
        return <TZLabel time={stringValue} showSeconds={definition.display_type === 'datetime'} />
    }
    if (definition?.display_type === 'boolean') {
        return stringValue === 'true' || stringValue === '1' ? <IconCheck /> : <IconX className="text-muted" />
    }
    if (definition?.display_type === 'link') {
        return todayRailNav ? (
            <Button
                variant="link-foreground"
                size="sm"
                nativeButton={false}
                render={<LinkPrimitive to={stringValue} target="_blank" />}
            >
                {stringValue}
            </Button>
        ) : (
            <Link to={stringValue} target="_blank" targetBlankIcon={false}>
                {stringValue}
            </Link>
        )
    }
    if (definition?.display_type === 'select') {
        const option = definition.options?.find((candidate) => candidate.label === stringValue)
        return (
            <span className="inline-flex items-center gap-1.5">
                {option &&
                    (todayRailNav ? (
                        <QuillOptionColorSwatch colorToken={option.color as DataColorToken} />
                    ) : (
                        <LemonColorGlyph colorToken={option.color as DataColorToken} size="small" />
                    ))}
                <span>{stringValue}</span>
            </span>
        )
    }
    return <span>{definition ? formatCustomPropertyValue(stringValue, definition) : stringValue}</span>
}

function PreviewResult({
    preview,
    current,
    ruleGroups,
    definitionsById,
}: {
    preview: NonNullable<accountTrackRulesLogicValues['previewResponse']>
    current: boolean
    ruleGroups: readonly AccountTrackRuleGroupApi[]
    definitionsById: Record<string, AccountsTableCustomPropertyDefinition>
}): JSX.Element {
    const [sampleKind, setSampleKind] = useState<PreviewSampleKind>('included')
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')
    const samples = sampleKind === 'included' ? preview.tracked_samples : preview.ignored_samples
    const ruleColumns = getPreviewRuleColumns(ruleGroups, definitionsById)
    const columns: LemonTableColumns<AccountTrackRuleSampleApi> = [
        {
            title: 'Account',
            render: (_, account) => (
                <AccountNameCell
                    accountId={account.id}
                    name={account.name}
                    externalId={account.external_id}
                    target="_blank"
                />
            ),
        },
        ...ruleColumns.map(({ key, label, definition }) => ({
            title: label,
            render: (_: unknown, account: AccountTrackRuleSampleApi) => (
                <PreviewRuleValue value={account.rule_values[key]} definition={definition} />
            ),
        })),
    ]

    if (todayRailNav) {
        return (
            <Card size="sm">
                <CardContent className="flex flex-col gap-4">
                    <div className="flex flex-wrap items-center gap-2">
                        <Text size="sm" render={<span className="m-0 font-semibold" />}>
                            Preview for version {preview.config_version}
                        </Text>
                        <Badge variant={current ? 'success' : 'warning'}>{current ? 'Current' : 'Stale'}</Badge>
                    </div>
                    <div className="@container">
                        <div className="grid grid-cols-2 gap-3 @min-[40rem]:grid-cols-4">
                            {PREVIEW_METRICS.map(({ key, deltaKey, label, tooltip }) => {
                                const delta = deltaKey ? preview[deltaKey] : 0
                                return (
                                    <div key={key} className="flex flex-col gap-1">
                                        <QuillTooltip>
                                            <TooltipTrigger
                                                render={
                                                    <Text
                                                        size="xs"
                                                        variant="muted"
                                                        className="cursor-help border-b border-dotted w-fit"
                                                    />
                                                }
                                            >
                                                {label}
                                            </TooltipTrigger>
                                            <TooltipContent className="max-w-80">{tooltip}</TooltipContent>
                                        </QuillTooltip>
                                        <Text size="lg" render={<span className="m-0 font-semibold" />}>
                                            <span translate="no">{preview[key].toLocaleString()}</span>
                                            {delta > 0 && (
                                                <Text variant="muted" render={<span className="m-0" />}>
                                                    {' '}
                                                    (+{delta.toLocaleString()})
                                                </Text>
                                            )}
                                        </Text>
                                    </div>
                                )
                            })}
                        </div>
                    </div>
                    <div className="flex flex-wrap items-center justify-between gap-3">
                        <Text size="sm" render={<span className="m-0 font-semibold" />}>
                            Preview results
                        </Text>
                        <ToggleGroup
                            className="flex-wrap"
                            aria-label="Preview results"
                            value={[sampleKind]}
                            onValueChange={(next: string[]) => {
                                if (next[0]) {
                                    setSampleKind(next[0] as PreviewSampleKind)
                                }
                            }}
                        >
                            {PREVIEW_SAMPLE_OPTIONS.map((option) => (
                                <ToggleGroupItem key={option.value} value={option.value}>
                                    {option.label}
                                </ToggleGroupItem>
                            ))}
                        </ToggleGroup>
                    </div>
                    <Table fullWidth className="rounded-md border border-border">
                        <TableHeader>
                            <TableRow>
                                <TableHead>Account</TableHead>
                                {ruleColumns.map(({ key, label }) => (
                                    <TableHead key={key}>{label}</TableHead>
                                ))}
                            </TableRow>
                        </TableHeader>
                        {samples.length === 0 ? (
                            <TableEmpty>
                                <Empty>
                                    <EmptyHeader>
                                        <EmptyTitle>{`No ${sampleKind} accounts`}</EmptyTitle>
                                    </EmptyHeader>
                                </Empty>
                            </TableEmpty>
                        ) : (
                            <TableBody>
                                {samples.map((account) => (
                                    <TableRow key={account.id}>
                                        <TableCell>
                                            <AccountNameCell
                                                accountId={account.id}
                                                name={account.name}
                                                externalId={account.external_id}
                                                target="_blank"
                                            />
                                        </TableCell>
                                        {ruleColumns.map(({ key, definition }) => (
                                            <TableCell key={key}>
                                                <PreviewRuleValue
                                                    value={account.rule_values[key]}
                                                    definition={definition}
                                                />
                                            </TableCell>
                                        ))}
                                    </TableRow>
                                ))}
                            </TableBody>
                        )}
                    </Table>
                </CardContent>
            </Card>
        )
    }

    return (
        <LemonCard hoverEffect={false} className="p-0 overflow-hidden">
            <div className="p-4 flex flex-col gap-3">
                <div className="flex items-center gap-2">
                    <span className="font-semibold">Preview for version {preview.config_version}</span>
                    <LemonTag type={current ? 'success' : 'warning'}>{current ? 'Current' : 'Stale'}</LemonTag>
                </div>
                <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                    {PREVIEW_METRICS.map(({ key, deltaKey, label, tooltip }) => {
                        const delta = deltaKey ? preview[deltaKey] : 0
                        return (
                            <div key={key}>
                                <Tooltip title={tooltip}>
                                    <span className="text-xs text-secondary cursor-help border-b border-dotted">
                                        {label}
                                    </span>
                                </Tooltip>
                                <div className="text-lg font-semibold">
                                    {preview[key].toLocaleString()}
                                    {delta > 0 && <span className="text-secondary"> (+{delta.toLocaleString()})</span>}
                                </div>
                            </div>
                        )
                    })}
                </div>
            </div>

            <div className="flex flex-wrap items-center justify-between gap-3 p-4">
                <div className="font-semibold">Preview results</div>
                <LemonSegmentedButton<PreviewSampleKind>
                    value={sampleKind}
                    onChange={setSampleKind}
                    options={PREVIEW_SAMPLE_OPTIONS}
                    size="small"
                />
            </div>
            <LemonTable
                embedded
                dataSource={[...samples]}
                columns={columns}
                emptyState={`No ${sampleKind} accounts`}
                className="border-t border-primary"
            />
        </LemonCard>
    )
}

function runStatusTone(status: string): 'success' | 'danger' | 'primary' {
    return status === 'completed' ? 'success' : TERMINAL_RUN_STATUSES.has(status) ? 'danger' : 'primary'
}

function runChangedLabel(run: AccountTrackRuleRunViewApi): string {
    return `${run.newly_ignored.toLocaleString()} ignored · ${run.restored.toLocaleString()} restored`
}

const RUN_STATUS_BADGE_VARIANT = { success: 'success', danger: 'destructive', primary: 'info' } as const

function RunHistory({ runs, loading }: { runs: AccountTrackRuleRunViewApi[]; loading: boolean }): JSX.Element {
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    if (todayRailNav) {
        if (loading && runs.length === 0) {
            return (
                <div className="flex flex-col gap-2">
                    <Skeleton className="h-10 w-full" />
                    <Skeleton className="h-10 w-full" />
                </div>
            )
        }

        return (
            <Table fullWidth className="rounded-md border border-border">
                <TableHeader>
                    <TableRow>
                        <TableHead>Started</TableHead>
                        <TableHead>Trigger</TableHead>
                        <TableHead>Version</TableHead>
                        <TableHead>Status</TableHead>
                        <TableHead>Tracked</TableHead>
                        <TableHead>Ignored</TableHead>
                        <TableHead>Changed</TableHead>
                        <TableHead>Duration</TableHead>
                        <TableHead>Error</TableHead>
                    </TableRow>
                </TableHeader>
                {runs.length === 0 ? (
                    <TableEmpty>
                        <Empty>
                            <EmptyHeader>
                                <EmptyTitle>No track rules runs yet</EmptyTitle>
                            </EmptyHeader>
                        </Empty>
                    </TableEmpty>
                ) : (
                    <TableBody>
                        {runs.map((run) => (
                            <TableRow key={run.id}>
                                <TableCell>
                                    <TZLabel time={run.started_at ?? run.created_at} />
                                </TableCell>
                                <TableCell>{getTrackRuleRunTriggerLabel(run.trigger)}</TableCell>
                                <TableCell>{run.config_version}</TableCell>
                                <TableCell>
                                    <Badge variant={RUN_STATUS_BADGE_VARIANT[runStatusTone(run.status)]}>
                                        {run.status}
                                    </Badge>
                                </TableCell>
                                <TableCell>{run.tracked}</TableCell>
                                <TableCell>{run.ignored}</TableCell>
                                <TableCell>{runChangedLabel(run)}</TableCell>
                                <TableCell>{getTrackRuleRunDuration(run)}</TableCell>
                                <TableCell>{run.error ?? '—'}</TableCell>
                            </TableRow>
                        ))}
                    </TableBody>
                )}
            </Table>
        )
    }

    const columns: LemonTableColumns<AccountTrackRuleRunViewApi> = [
        {
            title: 'Started',
            render: (_, run) => <TZLabel time={run.started_at ?? run.created_at} />,
        },
        {
            title: 'Trigger',
            render: (_, run) => getTrackRuleRunTriggerLabel(run.trigger),
        },
        {
            title: 'Version',
            dataIndex: 'config_version',
        },
        {
            title: 'Status',
            render: (_, run) => <LemonTag type={runStatusTone(run.status)}>{run.status}</LemonTag>,
        },
        {
            title: 'Tracked',
            dataIndex: 'tracked',
        },
        {
            title: 'Ignored',
            dataIndex: 'ignored',
        },
        {
            title: 'Changed',
            render: (_, run) => runChangedLabel(run),
        },
        {
            title: 'Duration',
            render: (_, run) => getTrackRuleRunDuration(run),
        },
        {
            title: 'Error',
            render: (_, run) => run.error ?? '—',
        },
    ]
    return <LemonTable dataSource={runs} columns={columns} loading={loading} emptyState="No track rules runs yet" />
}
