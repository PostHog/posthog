import { useActions, useValues } from 'kea'

import { IconPlus, IconTrash } from '@posthog/icons'
import {
    LemonBanner,
    LemonButton,
    LemonCard,
    LemonDivider,
    LemonSwitch,
    LemonTable,
    LemonTableColumns,
    LemonTag,
} from '@posthog/lemon-ui'

import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { TZLabel } from 'lib/components/TZLabel'
import { TeamMembershipLevel } from 'lib/constants'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'

import { PropertyFilterType, PropertyOperator, type AnyPropertyFilter } from '~/types'

import { accountsColumnConfigLogic } from 'products/customer_analytics/frontend/components/Accounts/accountsColumnConfigLogic'
import {
    ACCOUNT_FIELD_TAXONOMIC_OPTIONS,
    ACCOUNT_FILTER_OPERATOR_ALLOWLIST,
    accountFilterStaticValueOptions,
    type AccountFilter,
    isAccountPropertyFilter,
} from 'products/customer_analytics/frontend/components/Accounts/accountsPropertyFilters'
import type {
    AccountTrackRuleConditionApi,
    AccountTrackRuleGroupApi,
    AccountTrackRuleRunViewApi,
    CustomPropertyDefinitionApi,
} from 'products/customer_analytics/frontend/generated/api.schemas'

import { accountTrackRulesLogic, type accountTrackRulesLogicValues } from './accountTrackRulesLogic'

const TRACK_RULE_ACCOUNT_FIELDS = ACCOUNT_FIELD_TAXONOMIC_OPTIONS.filter(
    ({ id }) => id !== 'ignored_at' && id !== 'churned_at'
)
const TERMINAL_RUN_STATUSES = new Set(['completed', 'failed', 'stale'])

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
    definitionsById: Record<string, CustomPropertyDefinitionApi>
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
        saveResponseLoading,
        previewResponse,
        previewResponseLoading,
        previewIsCurrent,
        runs,
        runsLoading,
        canRun,
        currentRunLoading,
    } = useValues(accountTrackRulesLogic)
    const { setEnabled, addGroup, updateGroup, removeGroup, saveConfig, loadPreview, startRun, loadRuns } =
        useActions(accountTrackRulesLogic)
    const { customPropertyTaxonomicOptions, customPropertyDefinitionsById, customPropertyDefinitionsLoading } =
        useValues(accountsColumnConfigLogic)
    const restrictionReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })

    const confirmRun = (): void => {
        if (!previewResponse || !previewIsCurrent) {
            return
        }
        LemonDialog.open({
            title: 'Apply these Track Rules?',
            description: `This will track ${previewResponse.tracked.toLocaleString()} active accounts and ignore ${previewResponse.ignored.toLocaleString()}. Churned accounts will not change.`,
            primaryButton: {
                children: 'Run now',
                onClick: startRun,
            },
            secondaryButton: { children: 'Cancel' },
        })
    }

    if ((configLoading && !config) || customPropertyDefinitionsLoading) {
        return <div className="text-secondary">Loading Track Rules…</div>
    }

    return (
        <div className="flex flex-col gap-4 max-w-240" data-attr="account-track-rules">
            <div className="flex items-start justify-between gap-4">
                <div>
                    <h2 className="text-lg font-semibold mb-1">Account Track Rules</h2>
                    <p className="text-secondary mb-0">
                        Accounts matching any group stay tracked. Conditions inside a group must all match. Saving does
                        not change accounts until you preview and run the saved version. Turning rules off stops future
                        runs and does not restore accounts.
                    </p>
                </div>
                <LemonSwitch
                    checked={draft.enabled}
                    onChange={setEnabled}
                    label="Enabled"
                    disabledReason={restrictionReason}
                />
            </div>

            {draft.groups.map((group, index) => (
                <LemonCard key={index} className="p-4 flex flex-col gap-3">
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
                    <PropertyFilters
                        propertyFilters={
                            ruleGroupToAccountFilters(
                                group,
                                customPropertyDefinitionsById
                            ) as unknown as AnyPropertyFilter[]
                        }
                        onChange={(filters) =>
                            updateGroup(index, accountFiltersToRuleGroup(filters as unknown as AccountFilter[]))
                        }
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
                        staticValueOptions={accountFilterStaticValueOptions}
                        editable={!restrictionReason}
                        disabledReason={restrictionReason ?? undefined}
                        hasRowOperator={false}
                    />
                    <span className="text-xs text-secondary">All conditions in this group use AND.</span>
                </LemonCard>
            ))}

            <div>
                <LemonButton
                    type="secondary"
                    icon={<IconPlus />}
                    onClick={addGroup}
                    disabledReason={
                        restrictionReason || (draft.groups.length >= 20 ? 'A rule can have up to 20 groups' : undefined)
                    }
                >
                    Add OR group
                </LemonButton>
            </div>

            {hasUnsavedChanges && (
                <LemonBanner type="info">This draft differs from saved version {config?.version ?? 0}.</LemonBanner>
            )}
            {previewResponse && !previewIsCurrent && (
                <LemonBanner type="warning">
                    The last preview is stale. Save and preview the current version.
                </LemonBanner>
            )}

            <div className="flex flex-wrap gap-2">
                <LemonButton
                    type="primary"
                    onClick={saveConfig}
                    loading={saveResponseLoading}
                    disabledReason={
                        restrictionReason ||
                        (!hasUnsavedChanges
                            ? 'No changes to save'
                            : !canSave
                              ? 'Add at least one condition to every group'
                              : undefined)
                    }
                >
                    Save draft
                </LemonButton>
                <LemonButton
                    type="secondary"
                    onClick={loadPreview}
                    loading={previewResponseLoading}
                    disabledReason={
                        restrictionReason ||
                        (hasUnsavedChanges ? 'Save this draft before previewing it' : undefined) ||
                        (!config?.groups.length ? 'Add and save at least one group' : undefined)
                    }
                >
                    Preview
                </LemonButton>
                <LemonButton
                    type="secondary"
                    onClick={confirmRun}
                    loading={currentRunLoading}
                    disabledReason={
                        restrictionReason ||
                        (!config?.enabled
                            ? 'Enable and save Track Rules before running them'
                            : !previewIsCurrent
                              ? 'Preview the current saved version first'
                              : !canRun
                                ? 'Another run is in progress'
                                : undefined)
                    }
                >
                    Run now
                </LemonButton>
            </div>

            {previewResponse && <PreviewResult preview={previewResponse} current={previewIsCurrent} />}

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

function PreviewResult({
    preview,
    current,
}: {
    preview: NonNullable<accountTrackRulesLogicValues['previewResponse']>
    current: boolean
}): JSX.Element {
    const counts = [
        ['Eligible active', preview.eligible_active],
        ['Tracked', preview.tracked],
        ['Ignored', preview.ignored],
        ['Newly ignored', preview.newly_ignored],
        ['Restored', preview.restored],
        ['Churned skipped', preview.skipped_churned],
    ] as const
    return (
        <LemonCard className="p-4 flex flex-col gap-3">
            <div className="flex items-center gap-2">
                <span className="font-semibold">Preview for version {preview.config_version}</span>
                <LemonTag type={current ? 'success' : 'warning'}>{current ? 'Current' : 'Stale'}</LemonTag>
            </div>
            <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
                {counts.map(([label, value]) => (
                    <div key={label}>
                        <div className="text-xs text-secondary">{label}</div>
                        <div className="text-lg font-semibold">{value.toLocaleString()}</div>
                    </div>
                ))}
            </div>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3 text-sm">
                <SampleList title="Tracked sample" names={preview.tracked_samples.map(({ name }) => name)} />
                <SampleList title="Ignored sample" names={preview.ignored_samples.map(({ name }) => name)} />
            </div>
        </LemonCard>
    )
}

function SampleList({ title, names }: { title: string; names: readonly string[] }): JSX.Element {
    return (
        <div>
            <div className="font-medium">{title}</div>
            <div className="text-secondary">{names.length ? names.join(', ') : 'No accounts'}</div>
        </div>
    )
}

function RunHistory({ runs, loading }: { runs: AccountTrackRuleRunViewApi[]; loading: boolean }): JSX.Element {
    const columns: LemonTableColumns<AccountTrackRuleRunViewApi> = [
        {
            title: 'Started',
            render: (_, run) => <TZLabel time={run.started_at ?? run.created_at} />,
        },
        {
            title: 'Version',
            dataIndex: 'config_version',
        },
        {
            title: 'Status',
            render: (_, run) => (
                <LemonTag
                    type={
                        run.status === 'completed'
                            ? 'success'
                            : TERMINAL_RUN_STATUSES.has(run.status)
                              ? 'danger'
                              : 'primary'
                    }
                >
                    {run.status}
                </LemonTag>
            ),
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
            render: (_, run) =>
                `${run.newly_ignored.toLocaleString()} ignored · ${run.restored.toLocaleString()} restored`,
        },
        {
            title: 'Error',
            render: (_, run) => run.error ?? '—',
        },
    ]
    return <LemonTable dataSource={runs} columns={columns} loading={loading} emptyState="No Track Rules runs yet" />
}
