import { deepEqual as equal } from 'fast-equals'
import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconPlus, IconTrash } from '@posthog/icons'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TeamMembershipLevel } from 'lib/constants'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { LemonLabel } from 'lib/lemon-ui/LemonLabel'
import { LemonSelect } from 'lib/lemon-ui/LemonSelect'
import { LemonTable } from 'lib/lemon-ui/LemonTable'
import { LemonTag } from 'lib/lemon-ui/LemonTag'
import { Link } from 'lib/lemon-ui/Link'
import { uuid } from 'lib/utils/dom'
import { teamLogic } from 'scenes/teamLogic'

import { CustomBotDefinition, CustomBotField, CustomBotMatcher } from '~/queries/schema/schema-general'

import {
    CUSTOM_BOT_CATEGORY,
    CUSTOM_BOT_CATEGORY_OPTIONS,
    CUSTOM_BOT_FIELD_OPTIONS,
    MAX_CUSTOM_BOT_DEFINITIONS,
    defaultMatcherFor,
    fieldLabel,
    matcherOptionsFor,
    matchesValue,
    patternPlaceholderFor,
    sanitizeCustomBotDefinitions,
    validateCustomBotDefinition,
} from './customBotDefinitionsUtils'

function newDefinition(): CustomBotDefinition {
    return {
        id: uuid(),
        name: '',
        key: CustomBotField.RawUserAgent,
        pattern: '',
        matcher: CustomBotMatcher.Contains,
        category: CUSTOM_BOT_CATEGORY,
    }
}

export function CustomBotDefinitions(): JSX.Element {
    const { currentTeam, currentTeamLoading } = useValues(teamLogic)
    const { updateCurrentTeam } = useActions(teamLogic)

    // The saved state is whatever the server currently holds, so a save that the backend rejects
    // leaves the editor dirty and retryable instead of falsely reading as saved.
    const savedDefinitions = currentTeam?.modifiers?.customBotDefinitions ?? []
    const [definitions, setDefinitions] = useState<CustomBotDefinition[]>(savedDefinitions)
    const [testValues, setTestValues] = useState<Partial<Record<CustomBotField, string>>>({})

    const restrictedReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })
    const canEdit = !restrictedReason

    const firstError = definitions.map(validateCustomBotDefinition).find(Boolean)
    // Sanitize both sides: a rule written through the API can lack the optional category or carry
    // unpadded whitespace, and a pristine editor must not read as dirty for normalization alone.
    const isUnchanged = equal(sanitizeCustomBotDefinitions(definitions), sanitizeCustomBotDefinitions(savedDefinitions))
    const testedFields = CUSTOM_BOT_FIELD_OPTIONS.filter((option) =>
        definitions.some((definition) => definition.key === option.value)
    )
    const matched = definitions.filter((definition) => matchesValue(definition, testValues[definition.key] ?? ''))
    // Only values for a property still in use count as test input, so removing a rule does not leave
    // a stale value showing a phantom "no match".
    const hasTestInput = testedFields.some((field) => testValues[field.value]?.trim())
    // $ip is dropped on ingest when a project anonymizes IPs, so a range would never match.
    const ipRulesAreDead =
        currentTeam?.anonymize_ips && definitions.some((definition) => definition.key === CustomBotField.IP)

    const updateDefinition = (id: string, update: Partial<CustomBotDefinition>): void => {
        setDefinitions(definitions.map((d) => (d.id === id ? { ...d, ...update } : d)))
    }

    const changeKey = (definition: CustomBotDefinition, key: CustomBotField): void => {
        // Regex works on every property, so treat it as a deliberate choice and keep it. Anything
        // else follows the new property, which moves an IP rule onto ranges.
        const matcher = definition.matcher === CustomBotMatcher.Regex ? CustomBotMatcher.Regex : defaultMatcherFor(key)
        updateDefinition(definition.id, { key, matcher })
    }

    const save = (): void => {
        const sanitized = sanitizeCustomBotDefinitions(definitions)
        setDefinitions(sanitized)
        // On success the team reloads with these definitions and isUnchanged flips to true; on a
        // rejected save the team is unchanged, so the editor stays dirty and the error is actionable.
        updateCurrentTeam({
            modifiers: { ...currentTeam?.modifiers, customBotDefinitions: sanitized },
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
                Match the user agent to catch a crawler that names itself, or the IP address to catch one that sends a
                browser user agent from a range you know.{' '}
                <Link to="https://posthog.com/docs/web-analytics/bot-detection">Read more about bot detection</Link>
            </p>

            <LemonTable
                dataSource={definitions}
                emptyState="No bots added yet. PostHog's built-in list still applies. Add one to extend it."
                columns={[
                    {
                        title: 'Name',
                        key: 'name',
                        width: '22%',
                        render: (_, definition) => (
                            <LemonInput
                                value={definition.name}
                                onChange={(name) => updateDefinition(definition.id, { name })}
                                placeholder="Acme scraper"
                                disabledReason={restrictedReason}
                            />
                        ),
                    },
                    {
                        title: 'Matches when',
                        key: 'pattern',
                        render: (_, definition) => {
                            const error = validateCustomBotDefinition(definition)
                            return (
                                <div className="flex flex-col gap-1">
                                    <div className="flex items-center gap-2">
                                        <LemonSelect
                                            value={definition.key}
                                            options={CUSTOM_BOT_FIELD_OPTIONS}
                                            onChange={(key) => changeKey(definition, key)}
                                            disabledReason={restrictedReason}
                                        />
                                        <LemonSelect
                                            value={definition.matcher}
                                            options={matcherOptionsFor(definition.key)}
                                            onChange={(matcher) => updateDefinition(definition.id, { matcher })}
                                            disabledReason={restrictedReason}
                                        />
                                        <LemonInput
                                            className="flex-1 font-mono"
                                            value={definition.pattern}
                                            onChange={(pattern) => updateDefinition(definition.id, { pattern })}
                                            placeholder={patternPlaceholderFor(definition.key, definition.matcher)}
                                            status={error ? 'danger' : undefined}
                                            disabledReason={restrictedReason}
                                        />
                                    </div>
                                    {error ? <span className="text-danger text-xs">{error}</span> : null}
                                </div>
                            )
                        },
                    },
                    {
                        title: 'Category',
                        key: 'category',
                        width: '18%',
                        render: (_, definition) => (
                            <LemonSelect
                                className="w-full"
                                value={definition.category || CUSTOM_BOT_CATEGORY}
                                options={CUSTOM_BOT_CATEGORY_OPTIONS}
                                onChange={(category) => updateDefinition(definition.id, { category })}
                                disabledReason={restrictedReason}
                            />
                        ),
                    },
                    {
                        key: 'remove',
                        width: 0,
                        render: (_, definition) =>
                            canEdit ? (
                                <LemonButton
                                    icon={<IconTrash />}
                                    size="small"
                                    tooltip="Remove"
                                    onClick={() => setDefinitions(definitions.filter((d) => d.id !== definition.id))}
                                />
                            ) : null,
                    },
                ]}
            />

            {canEdit ? (
                <div className="flex items-center gap-2">
                    <LemonButton
                        type="secondary"
                        icon={<IconPlus />}
                        onClick={() => setDefinitions([...definitions, newDefinition()])}
                        disabledReason={
                            definitions.length >= MAX_CUSTOM_BOT_DEFINITIONS
                                ? `You can define at most ${MAX_CUSTOM_BOT_DEFINITIONS} bots`
                                : undefined
                        }
                    >
                        Add bot
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        onClick={save}
                        loading={currentTeamLoading}
                        disabledReason={
                            currentTeamLoading
                                ? 'Saving'
                                : firstError
                                  ? 'Fix the errors above first'
                                  : isUnchanged
                                    ? 'No changes to save'
                                    : undefined
                        }
                    >
                        Save
                    </LemonButton>
                </div>
            ) : null}

            {ipRulesAreDead ? (
                <LemonBanner type="warning">
                    This project anonymizes IP addresses, so events arrive without one and a rule on the IP address
                    never matches. Turn off IP anonymization in Project settings, or match on another property.
                </LemonBanner>
            ) : null}

            {testedFields.length > 0 ? (
                <div className="flex flex-col gap-2">
                    <LemonLabel info="Only your own bots are checked here. A real query also matches PostHog's built-in list, after your rules.">
                        Test a value
                    </LemonLabel>
                    {testedFields.map((field) => (
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
                            {matched.map((definition) => (
                                <LemonTag key={definition.id} type="success">
                                    {definition.name || fieldLabel(definition.key)}
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

            {savedDefinitions.length > 0 ? (
                <LemonBanner type="info">
                    Changes apply to new and existing data. Refresh an insight or dashboard to see them applied.
                </LemonBanner>
            ) : null}
        </div>
    )
}
