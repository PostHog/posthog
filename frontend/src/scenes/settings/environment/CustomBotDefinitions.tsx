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

import { CustomBotDefinition, CustomBotMatcher } from '~/queries/schema/schema-general'

import {
    CUSTOM_BOT_CATEGORY,
    CUSTOM_BOT_CATEGORY_OPTIONS,
    MAX_CUSTOM_BOT_DEFINITIONS,
    matchesUserAgent,
    sanitizeCustomBotDefinitions,
    validateCustomBotDefinition,
} from './customBotDefinitions'

const MATCHER_OPTIONS = [
    { value: CustomBotMatcher.Contains, label: 'contains' },
    { value: CustomBotMatcher.Regex, label: 'matches regex' },
]

function newDefinition(): CustomBotDefinition {
    return {
        id: uuid(),
        name: '',
        pattern: '',
        matcher: CustomBotMatcher.Contains,
        category: CUSTOM_BOT_CATEGORY,
    }
}

export function CustomBotDefinitions(): JSX.Element {
    const { currentTeam, currentTeamLoading } = useValues(teamLogic)
    const { updateCurrentTeam } = useActions(teamLogic)

    const [savedDefinitions, setSavedDefinitions] = useState<CustomBotDefinition[]>(
        () => currentTeam?.modifiers?.customBotDefinitions ?? []
    )
    const [definitions, setDefinitions] = useState<CustomBotDefinition[]>(savedDefinitions)
    const [testUserAgent, setTestUserAgent] = useState('')

    const restrictedReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })
    const canEdit = !restrictedReason

    const errors = definitions.map(validateCustomBotDefinition)
    const firstError = errors.find(Boolean)
    const isUnchanged = equal(definitions, savedDefinitions)

    const updateDefinition = (id: string, update: Partial<CustomBotDefinition>): void => {
        setDefinitions(definitions.map((d) => (d.id === id ? { ...d, ...update } : d)))
    }

    const save = (): void => {
        const sanitized = sanitizeCustomBotDefinitions(definitions)
        updateCurrentTeam({
            modifiers: { ...currentTeam?.modifiers, customBotDefinitions: sanitized },
        })
        setDefinitions(sanitized)
        setSavedDefinitions(sanitized)
    }

    const matchedName = testUserAgent
        ? definitions.find((definition) => matchesUserAgent(definition, testUserAgent))?.name
        : undefined

    return (
        <div className="flex flex-col gap-4">
            <p className="mb-0">
                A bot you add here counts as a bot everywhere <code>Is bot</code> is available, including insights, web
                analytics, and SQL. The built-in list covers crawlers that identify themselves, like GPTBot and
                Googlebot.
            </p>
            <p className="mb-0">
                Matching only looks at the user agent a visitor sends, so this does not catch traffic that reports
                itself as a browser.{' '}
                <Link to="https://posthog.com/docs/web-analytics/bot-detection">Read more about bot detection</Link>
            </p>

            <LemonTable
                dataSource={definitions}
                emptyState="No bots added yet. PostHog's built-in list still applies. Add one to extend it."
                columns={[
                    {
                        title: 'Name',
                        key: 'name',
                        width: '25%',
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
                        title: 'User agent',
                        key: 'pattern',
                        render: (_, definition) => {
                            const error = validateCustomBotDefinition(definition)
                            return (
                                <div className="flex flex-col gap-1">
                                    <div className="flex items-center gap-2">
                                        <LemonSelect
                                            value={definition.matcher}
                                            options={MATCHER_OPTIONS}
                                            onChange={(matcher) => updateDefinition(definition.id, { matcher })}
                                            disabledReason={restrictedReason}
                                        />
                                        <LemonInput
                                            className="flex-1 font-mono"
                                            value={definition.pattern}
                                            onChange={(pattern) => updateDefinition(definition.id, { pattern })}
                                            placeholder={
                                                definition.matcher === CustomBotMatcher.Regex
                                                    ? 'AcmeBot/[0-9]+'
                                                    : 'AcmeBot'
                                            }
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
                        width: '20%',
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

            {definitions.length > 0 ? (
                <div className="flex flex-col gap-2">
                    <LemonLabel>Test a user agent</LemonLabel>
                    <LemonInput
                        className="font-mono"
                        value={testUserAgent}
                        onChange={setTestUserAgent}
                        placeholder="Paste a user agent to see if one of your bots matches it"
                    />
                    {testUserAgent ? (
                        matchedName ? (
                            <span>
                                Matches <LemonTag type="success">{matchedName}</LemonTag>
                            </span>
                        ) : (
                            <span className="text-secondary">
                                None of your bots match this. PostHog's built-in list may still classify it as a bot.
                            </span>
                        )
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
