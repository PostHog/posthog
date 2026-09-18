import { deepEqual as equal } from 'fast-equals'
import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconPlus } from '@posthog/icons'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { VerticalNestedDND } from 'lib/components/VerticalNestedDND/VerticalNestedDND'
import { TeamMembershipLevel } from 'lib/constants'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { LemonLabel } from 'lib/lemon-ui/LemonLabel'
import { LemonSelect } from 'lib/lemon-ui/LemonSelect'
import { LemonTag } from 'lib/lemon-ui/LemonTag'
import { Link } from 'lib/lemon-ui/Link'
import { uuid } from 'lib/utils/dom'
import { teamLogic } from 'scenes/teamLogic'

import { CustomBotCondition, CustomBotField, CustomBotMatcher, CustomBotRule } from '~/queries/schema/schema-general'
import { FilterLogicalOperator } from '~/types'

import {
    CUSTOM_BOT_CATEGORY,
    CUSTOM_BOT_CATEGORY_OPTIONS,
    CUSTOM_BOT_FIELD_OPTIONS,
    MAX_CONDITIONS_PER_RULE,
    MAX_CUSTOM_BOT_RULES,
    MAX_TOTAL_CONDITIONS,
    defaultMatcherFor,
    fieldLabel,
    matcherLabel,
    matcherOptionsFor,
    patternPlaceholderFor,
    ruleMatchesValues,
    sanitizeCustomBotRules,
    parseCustomBotRules,
    validateCustomBotCondition,
    validateCustomBotRule,
    validateCustomBotRuleSet,
} from './customBotRulesUtils'

// Lowercase: the labels render mid-sentence ("when all conditions are met").
const combinerOptions = [
    { label: 'all', value: FilterLogicalOperator.And },
    { label: 'any', value: FilterLogicalOperator.Or },
]

function categoryLabel(category: string | undefined): string {
    const value = category || CUSTOM_BOT_CATEGORY
    return CUSTOM_BOT_CATEGORY_OPTIONS.find((option) => option.value === value)?.label ?? value
}

/** The list without edit affordances: the shared editor always renders drag handles and delete
buttons, which would look actionable to someone whose changes can never be saved. */
function ReadOnlyBotRules({ rules }: { rules: CustomBotRule[] }): JSX.Element {
    return (
        <div className="flex flex-col gap-2">
            {rules.map((rule) => (
                <div key={rule.id} className="border rounded p-3 flex flex-col gap-1">
                    <div className="flex items-center gap-2 flex-wrap">
                        <span className="font-semibold">{rule.name}</span>
                        <LemonTag>{categoryLabel(rule.category)}</LemonTag>
                    </div>
                    {rule.items.length > 1 ? (
                        <span className="text-muted text-xs">
                            When {rule.combiner === FilterLogicalOperator.Or ? 'any' : 'all'} of these conditions are
                            met:
                        </span>
                    ) : null}
                    {rule.items.map((condition) => (
                        <span key={condition.id} className="text-sm">
                            {fieldLabel(condition.key)} {matcherLabel(condition.matcher)}{' '}
                            <code>{condition.pattern}</code>
                        </span>
                    ))}
                </div>
            ))}
        </div>
    )
}

function newCondition(): CustomBotCondition {
    return {
        id: uuid(),
        key: CustomBotField.RawUserAgent,
        matcher: CustomBotMatcher.Contains,
        pattern: '',
    }
}

function newRule(): CustomBotRule {
    return {
        id: uuid(),
        name: '',
        category: CUSTOM_BOT_CATEGORY,
        combiner: FilterLogicalOperator.And,
        items: [newCondition()],
    }
}

export function CustomBotRules(): JSX.Element {
    const { currentTeam, currentTeamLoading } = useValues(teamLogic)
    const { updateCurrentTeam } = useActions(teamLogic)

    // The saved state is whatever the server currently holds, so a save that the backend rejects
    // leaves the editor dirty and retryable instead of falsely reading as saved.
    const rawSavedRules = currentTeam?.modifiers?.customBotDefinitions
    const savedRules = parseCustomBotRules(rawSavedRules)
    // A save writes the parsed list back in full, so entries that did not parse would be removed
    // silently. Tell the user instead of losing them without a trace.
    const droppedCount = (Array.isArray(rawSavedRules) ? rawSavedRules.length : 0) - savedRules.length
    const [rules, setRules] = useState<CustomBotRule[]>(savedRules)
    const [testValues, setTestValues] = useState<Partial<Record<CustomBotField, string>>>({})

    const restrictedReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })
    const canEdit = !restrictedReason

    const anyRuleError = rules.map(validateCustomBotRule).find(Boolean)
    const setError = validateCustomBotRuleSet(rules)
    const totalConditions = rules.reduce((sum, rule) => sum + rule.items.length, 0)
    // Sanitize both sides: a rule written through the API can lack the optional category or carry
    // unpadded whitespace, and a pristine editor must not read as dirty for normalization alone.
    const isUnchanged = equal(sanitizeCustomBotRules(rules), sanitizeCustomBotRules(savedRules))
    const usedFields = CUSTOM_BOT_FIELD_OPTIONS.filter((option) =>
        rules.some((rule) => rule.items.some((condition) => condition.key === option.value))
    )
    const matched = rules.filter((rule) => ruleMatchesValues(rule, testValues))
    // Only values for a property still in use count as test input, so removing a rule does not leave
    // a stale value showing a phantom "no match".
    const hasTestInput = usedFields.some((field) => testValues[field.value]?.trim())
    // $ip is dropped on ingest when a project anonymizes IPs, so a range would never match.
    const ipRulesAreDead =
        currentTeam?.anonymize_ips &&
        rules.some((rule) => rule.items.some((condition) => condition.key === CustomBotField.IP))

    const save = (): void => {
        // On success the team reloads with these rules and isUnchanged flips to true; on a
        // rejected save the team is unchanged, so the editor stays dirty and the error is actionable.
        updateCurrentTeam({
            modifiers: { ...currentTeam?.modifiers, customBotDefinitions: sanitizeCustomBotRules(rules) },
        })
    }

    return (
        <div className="flex flex-col gap-4">
            <p className="mb-0">
                A bot you add here counts as a bot everywhere <code>Is bot</code> is available, including insights, web
                analytics, and SQL. PostHog's built-in list already covers crawlers that identify themselves, like
                GPTBot and Googlebot. Your rules are checked first, so you can give one of those a different name or
                category.
            </p>
            <p className="mb-0">
                Match the user agent to catch a crawler that names itself, the IP address to catch one that sends a
                browser user agent from a range you know, or combine conditions to catch one that only stands out
                through a combination, like an 800x600 screen.{' '}
                <Link to="https://posthog.com/docs/web-analytics/bot-detection">Read more about bot detection</Link>
            </p>

            {rules.length === 0 ? (
                <p className="text-muted mb-0">
                    No bots added yet. PostHog's built-in list still applies. Add one to extend it.
                </p>
            ) : null}

            {droppedCount > 0 ? (
                <LemonBanner type="warning">
                    {droppedCount === 1 ? 'One saved rule' : `${droppedCount} saved rules`} could not be read and will
                    be removed if you save. Contact support if you did not expect this.
                </LemonBanner>
            ) : null}

            {!canEdit ? (
                <ReadOnlyBotRules rules={rules} />
            ) : (
                <VerticalNestedDND<CustomBotCondition, CustomBotRule>
                    initialItems={rules}
                    onChange={setRules}
                    renderContainerItem={(rule, { updateContainerItem }) => {
                        const ruleError = validateCustomBotRule(rule)
                        return (
                            <div className="flex flex-col gap-2">
                                <div className="flex flex-row items-center gap-2 flex-wrap">
                                    <span>Flag as bot</span>
                                    <LemonInput
                                        className="flex-1 min-w-40"
                                        value={rule.name}
                                        onChange={(name) => updateContainerItem({ ...rule, name })}
                                        placeholder="Acme scraper"
                                        disabledReason={restrictedReason}
                                    />
                                    <span>in category</span>
                                    <LemonSelect
                                        value={rule.category || CUSTOM_BOT_CATEGORY}
                                        options={CUSTOM_BOT_CATEGORY_OPTIONS}
                                        onChange={(category) => updateContainerItem({ ...rule, category })}
                                        disabledReason={restrictedReason}
                                    />
                                </div>
                                {rule.items.length === 1 ? (
                                    <span>when this condition is met</span>
                                ) : (
                                    <div className="flex flex-row items-center gap-2">
                                        <span>when</span>
                                        <LemonSelect
                                            value={rule.combiner}
                                            options={combinerOptions}
                                            onChange={(combiner) => updateContainerItem({ ...rule, combiner })}
                                            disabledReason={restrictedReason}
                                        />
                                        <span>conditions are met</span>
                                    </div>
                                )}
                                {ruleError && !rule.items.some(validateCustomBotCondition) ? (
                                    <span className="text-danger text-xs">{ruleError}</span>
                                ) : null}
                            </div>
                        )
                    }}
                    renderChildItem={(condition, { updateChildItem }) => {
                        const error = validateCustomBotCondition(condition)
                        const changeKey = (key: CustomBotField): void => {
                            // Regex works on every property, so treat it as a deliberate choice and keep
                            // it. Anything else follows the new property, which moves an IP condition
                            // onto ranges and a screen dimension onto equality.
                            const matcher =
                                condition.matcher === CustomBotMatcher.Regex
                                    ? CustomBotMatcher.Regex
                                    : defaultMatcherFor(key)
                            updateChildItem({ ...condition, key, matcher })
                        }
                        return (
                            <div className="w-full flex flex-col gap-1">
                                <div className="flex flex-row items-center gap-2">
                                    <LemonSelect
                                        value={condition.key}
                                        options={CUSTOM_BOT_FIELD_OPTIONS}
                                        onChange={changeKey}
                                        disabledReason={restrictedReason}
                                    />
                                    <LemonSelect
                                        value={condition.matcher}
                                        options={matcherOptionsFor(condition.key)}
                                        onChange={(matcher) => updateChildItem({ ...condition, matcher })}
                                        disabledReason={restrictedReason}
                                    />
                                    <LemonInput
                                        className="flex-1 font-mono"
                                        value={condition.pattern}
                                        onChange={(pattern) => updateChildItem({ ...condition, pattern })}
                                        placeholder={patternPlaceholderFor(condition.key, condition.matcher)}
                                        status={error ? 'danger' : undefined}
                                        disabledReason={restrictedReason}
                                    />
                                </div>
                                {error ? <span className="text-danger text-xs">{error}</span> : null}
                            </div>
                        )
                    }}
                    renderAddChildItem={(rule, { onAddChild }) =>
                        canEdit ? (
                            <LemonButton
                                type="secondary"
                                icon={<IconPlus />}
                                onClick={() => onAddChild(rule.id)}
                                data-attr="custom-bot-rules-add-condition"
                                disabledReason={
                                    rule.items.length >= MAX_CONDITIONS_PER_RULE
                                        ? `A rule can have at most ${MAX_CONDITIONS_PER_RULE} conditions`
                                        : totalConditions >= MAX_TOTAL_CONDITIONS
                                          ? `You can have at most ${MAX_TOTAL_CONDITIONS} conditions across all rules`
                                          : undefined
                                }
                            >
                                Add condition
                            </LemonButton>
                        ) : null
                    }
                    renderAddContainerItem={({ onAddContainer }) =>
                        canEdit ? (
                            <LemonButton
                                type="secondary"
                                icon={<IconPlus />}
                                onClick={onAddContainer}
                                data-attr="custom-bot-rules-add-rule"
                                disabledReason={
                                    rules.length >= MAX_CUSTOM_BOT_RULES
                                        ? `You can define at most ${MAX_CUSTOM_BOT_RULES} bots`
                                        : totalConditions >= MAX_TOTAL_CONDITIONS
                                          ? `You can have at most ${MAX_TOTAL_CONDITIONS} conditions across all rules`
                                          : undefined
                                }
                            >
                                Add bot
                            </LemonButton>
                        ) : null
                    }
                    renderAdditionalControls={() =>
                        canEdit ? (
                            <LemonButton
                                type="primary"
                                onClick={save}
                                loading={currentTeamLoading}
                                data-attr="custom-bot-rules-save"
                                disabledReason={
                                    currentTeamLoading
                                        ? 'Saving'
                                        : anyRuleError
                                          ? 'Fix the errors above first'
                                          : (setError ?? (isUnchanged ? 'No changes to save' : undefined))
                                }
                            >
                                Save
                            </LemonButton>
                        ) : null
                    }
                    createNewContainerItem={newRule}
                    createNewChildItem={newCondition}
                />
            )}

            {ipRulesAreDead ? (
                <LemonBanner type="warning">
                    This project anonymizes IP addresses, so events arrive without one and a condition on the IP address
                    never matches. Turn off "Discard client IP data" in your project settings, or match on another
                    property.
                </LemonBanner>
            ) : null}

            {usedFields.length > 0 ? (
                <div className="flex flex-col gap-2">
                    <LemonLabel info="Only your own bots are checked here. A real query also matches PostHog's built-in list, after your rules.">
                        Test a value
                    </LemonLabel>
                    {usedFields.map((field) => (
                        <div key={field.value} className="flex items-center gap-2">
                            <span className="w-32 shrink-0 text-muted text-xs">{field.label}</span>
                            <LemonInput
                                className="flex-1 font-mono"
                                value={testValues[field.value] ?? ''}
                                onChange={(value) => setTestValues({ ...testValues, [field.value]: value })}
                                placeholder={
                                    field.value === CustomBotField.IP ? '192.0.2.55' : `Paste a ${field.label}`
                                }
                            />
                        </div>
                    ))}
                    {matched.length > 0 ? (
                        <span className="flex items-center gap-1 flex-wrap">
                            Matches
                            {matched.map((rule) => (
                                <LemonTag key={rule.id} type="success">
                                    {rule.name || fieldLabel(rule.items[0]?.key ?? CustomBotField.RawUserAgent)}
                                </LemonTag>
                            ))}
                        </span>
                    ) : hasTestInput ? (
                        <span className="text-muted">
                            No custom rule matched. PostHog's built-in list still applies.
                        </span>
                    ) : null}
                </div>
            ) : null}

            {savedRules.length > 0 ? (
                <LemonBanner type="info">
                    Changes apply to new and existing data. Refresh an insight or dashboard to see them applied.
                </LemonBanner>
            ) : null}
        </div>
    )
}
