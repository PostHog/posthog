import type { ApplyOp } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/setupPlanLogic'

import type { MarketingAnalyticsConfig } from '~/queries/schema/schema-general'

/** One line of a change preview: a setting, and what happens to it. */
export interface DiffLine {
    /** Human-facing setting name, e.g. "Custom source mappings". */
    setting: string
    /** What the change applies to within that setting, e.g. "Meta Ads". */
    subject?: string
    change: 'add' | 'remove' | 'update'
    /** Present for `update`; absent for add/remove. */
    before?: string
    after: string
}

export interface ApplyDiff {
    lines: DiffLine[]
    /** True when the op changes nothing — re-applying a mapping that already exists.
     * The UI says so rather than showing an empty diff, which reads as a bug. */
    isNoop: boolean
}

const SETTING_LABELS = {
    customSourceMappings: 'Custom source mappings',
    campaignNameMappings: 'Campaign name mappings',
    campaignFieldPreferences: 'Campaign matching',
    conversionGoals: 'Conversion goals',
} as const

function integrationLabel(integration: unknown): string {
    // Config keys are PascalCase source types ("GoogleAds"); split them for reading.
    return String(integration ?? '').replace(/([a-z])([A-Z])/g, '$1 $2')
}

/** Named as the goal editor names them, so approving a change doesn't require knowing
 * the schema. */
const GOAL_FIELD_LABELS: Record<string, string> = {
    counts_as_revenue: 'Each conversion is worth money',
    counts_as_customer: 'Counts as a new customer',
    conversion_goal_name: 'Name',
    math: 'Aggregation',
    math_property: 'Amount property',
    math_property_revenue_currency: 'Currency',
}

function goalFieldLabel(key: string): string {
    // A field added backend-first should look unpolished, not invisible.
    return GOAL_FIELD_LABELS[key] ?? key.replace(/_/g, ' ')
}

/** What a config-mutating op will change, derived from the same `ApplyOp` the server
 * will execute so the preview can't drift. Undescribable ops return no lines. */
export function buildApplyDiff(op: ApplyOp, config: MarketingAnalyticsConfig | null | undefined): ApplyDiff {
    const lines: DiffLine[] = []

    switch (op.op) {
        case 'add_custom_source_mapping': {
            const existing = config?.custom_source_mappings?.[op.integration as string] ?? []
            if (!existing.includes(op.raw_utm_source as string)) {
                lines.push({
                    setting: SETTING_LABELS.customSourceMappings,
                    subject: integrationLabel(op.integration),
                    change: 'add',
                    after: String(op.raw_utm_source),
                })
            }
            break
        }

        case 'remove_custom_source_mapping': {
            const existing = config?.custom_source_mappings?.[op.integration as string] ?? []
            if (existing.includes(op.raw_utm_source as string)) {
                lines.push({
                    setting: SETTING_LABELS.customSourceMappings,
                    subject: integrationLabel(op.integration),
                    change: 'remove',
                    after: String(op.raw_utm_source),
                })
            }
            break
        }

        case 'add_campaign_name_mapping': {
            const existing = config?.campaign_name_mappings?.[op.integration as string]?.[op.clean_name as string] ?? []
            const added = (op.raw_values as string[]).filter((value) => !existing.includes(value))
            for (const value of added) {
                lines.push({
                    setting: SETTING_LABELS.campaignNameMappings,
                    subject: `${integrationLabel(op.integration)} › ${op.clean_name}`,
                    change: 'add',
                    after: value,
                })
            }
            break
        }

        case 'remove_campaign_name_mapping': {
            const existing = config?.campaign_name_mappings?.[op.integration as string]?.[op.clean_name as string] ?? []
            const removed = (op.raw_values as string[]).filter((value) => existing.includes(value))
            for (const value of removed) {
                lines.push({
                    setting: SETTING_LABELS.campaignNameMappings,
                    subject: `${integrationLabel(op.integration)} › ${op.clean_name}`,
                    change: 'remove',
                    after: value,
                })
            }
            break
        }

        case 'set_campaign_field_preference': {
            // An absent preference means campaign_name, the documented default —
            // "not set" would suggest no matching was happening at all.
            const before =
                config?.campaign_field_preferences?.[op.integration as string]?.match_field ?? 'campaign_name'
            if (before !== op.match_field) {
                lines.push({
                    setting: SETTING_LABELS.campaignFieldPreferences,
                    subject: integrationLabel(op.integration),
                    change: 'update',
                    before: String(before).replace(/_/g, ' '),
                    after: String(op.match_field).replace(/_/g, ' '),
                })
            }
            break
        }

        case 'create_conversion_goal': {
            const goal = op.goal as Record<string, unknown>
            lines.push({
                setting: SETTING_LABELS.conversionGoals,
                change: 'add',
                after: String(goal.conversion_goal_name ?? goal.event ?? 'New goal'),
            })
            break
        }

        case 'delete_conversion_goal': {
            const goal = config?.conversion_goals?.find(
                (candidate) => candidate.conversion_goal_id === op.conversion_goal_id
            )
            lines.push({
                setting: SETTING_LABELS.conversionGoals,
                change: 'remove',
                after: goal?.conversion_goal_name ?? String(op.conversion_goal_id),
            })
            break
        }

        case 'update_conversion_goal': {
            const goal = config?.conversion_goals?.find(
                (candidate) => candidate.conversion_goal_id === op.conversion_goal_id
            )
            const patch = op.patch as Record<string, unknown>
            for (const [key, value] of Object.entries(patch)) {
                const before = goal ? (goal as unknown as Record<string, unknown>)[key] : undefined
                if (before === value) {
                    continue
                }
                lines.push({
                    setting: SETTING_LABELS.conversionGoals,
                    subject: `${goal?.conversion_goal_name ?? op.conversion_goal_id} › ${goalFieldLabel(key)}`,
                    change: 'update',
                    before: formatValue(before),
                    after: formatValue(value),
                })
            }
            break
        }
    }

    return { lines, isNoop: lines.length === 0 }
}

function formatValue(value: unknown): string {
    if (value === undefined || value === null) {
        return 'not set'
    }
    if (typeof value === 'boolean') {
        return value ? 'yes' : 'no'
    }
    return String(value)
}
