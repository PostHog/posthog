import { kea, path, connect, actions, reducers, selectors, listeners, events } from 'kea'
import { router } from 'kea-router'
import type { commandPaletteLogicType } from './commandPaletteLogicType'
import Fuse from 'fuse.js'
import { dashboardsModel } from '~/models/dashboardsModel'
import { Parser } from 'expr-eval'
import { DashboardType, InsightType } from '~/types'
import api from 'lib/api'
import { copyToClipboard, isMobile, isURL, sample, uniqueBy } from 'lib/utils'
import { userLogic } from 'scenes/userLogic'
import { personalAPIKeysLogic } from '../../../scenes/settings/user/personalAPIKeysLogic'
import { teamLogic } from 'scenes/teamLogic'
import posthog from 'posthog-js'
import { openCHQueriesDebugModal } from './DebugCHQueries'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { urls } from 'scenes/urls'
import { newDashboardLogic } from 'scenes/dashboard/newDashboardLogic'
import {
    IconAction,
    IconApps,
    IconBarChart,
    IconCalculate,
    IconCheckmark,
    IconCohort,
    IconComment,
    IconCorporate,
    IconCottage,
    IconEmojiPeople,
    IconFlag,
    IconFunnelHorizontal,
    IconGauge,
    IconGithub,
    IconKeyboard,
    IconLive,
    IconLockOpen,
    IconLogout,
    IconOpenInNew,
    IconPerson,
    IconPersonFilled,
    IconRecording,
    IconServer,
    IconSettings,
    IconTableChart,
    IconTools,
    IconTrendingFlat,
    IconTrendingUp,
} from 'lib/lemon-ui/icons'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

// If CommandExecutor returns CommandFlow, flow will be entered
export type CommandExecutor = () => CommandFlow | void

export interface CommandResultTemplate {
    icon: any // any, because Ant Design icons are some weird ForwardRefExoticComponent type
    display: string
    synonyms?: string[]
    prefixApplied?: string
    executor?: CommandExecutor | true // true means "just clear input"
    guarantee?: boolean // show result always and first, regardless of fuzzy search
}

export interface CommandResult extends CommandResultTemplate {
    source: Command | CommandFlow
}

export interface CommandResultDisplayable extends CommandResult {
    index: number
}

export type CommandResolver = (
    argument?: string,
    prefixApplied?: string
) => CommandResultTemplate[] | CommandResultTemplate | null

export interface Command {
    key: string // Unique command identification key
    prefixes?: string[] // Command prefixes, e.g. "go to". Prefix-less case is dynamic base command (e.g. Dashboard)
    resolver: CommandResolver | CommandResultTemplate[] | CommandResultTemplate // Resolver based on arguments (prefix excluded)
    scope: string
}

export interface CommandFlow {
    icon?: any
    instruction?: string
    resolver: CommandResolver | CommandResultTemplate[] | CommandResultTemplate
    scope?: string
    previousFlow?: CommandFlow | null
}

export interface CommandRegistrations {
    [commandKey: string]: Command
}

export type RegExpCommandPairs = [RegExp | null, Command][]

const RESULTS_MAX = 5

const GLOBAL_COMMAND_SCOPE = 'global'

function resolveCommand(source: Command | CommandFlow, argument?: string, prefixApplied?: string): CommandResult[] {
    // run resolver or use ready-made results
    let results = source.resolver instanceof Function ? source.resolver(argument, prefixApplied) : source.resolver
    if (!results) {
        return []
    } // skip if no result
    if (!Array.isArray(results)) {
        results = [results]
    } // work with a single result and with an array of results
    const resultsWithCommand: CommandResult[] = results.map((result) => {
        return { ...result, source }
    })
    return resultsWithCommand
}

export const commandPaletteLogic = kea<commandPaletteLogicType>([
    path(['lib', 'components', 'CommandPalette', 'commandPaletteLogic']),
    connect({
        actions: [personalAPIKeysLogic, ['createKey'], router, ['push']],
        values: [teamLogic, ['currentTeam'], userLogic, ['user'], featureFlagLogic, ['featureFlags']],
        logic: [preflightLogic],
    }),
    actions({
        hidePalette: true,
        showPalette: true,
        togglePalette: true,
        setInput: (input: string) => ({ input }),
        onArrowUp: true,
        onArrowDown: (maxIndex: number) => ({ maxIndex }),
        onMouseEnterResult: (index: number) => ({ index }),
        onMouseLeaveResult: true,
        executeResult: (result: CommandResult) => ({ result }),
        activateFlow: (flow: CommandFlow | null) => ({ flow }),
        backFlow: true,
        registerCommand: (command: Command) => ({ command }),
        deregisterCommand: (commandKey: string) => ({ commandKey }),
        setCustomCommand: (commandKey: string) => ({ commandKey }),
        deregisterScope: (scope: string) => ({ scope }),
    }),
    reducers({
        isPaletteShown: [
            false,
            {
                hidePalette: () => false,
                showPalette: () => true,
                togglePalette: (previousState) => !previousState,
            },
        ],
        keyboardResultIndex: [
            0,
            {
                setInput: () => 0,
                executeResult: () => 0,
                activateFlow: () => 0,
                backFlow: () => 0,
                onArrowUp: (previousIndex) => (previousIndex > 0 ? previousIndex - 1 : 0),
                onArrowDown: (previousIndex, { maxIndex }) => (previousIndex < maxIndex ? previousIndex + 1 : maxIndex),
            },
        ],
        hoverResultIndex: [
            null as number | null,
            {
                activateFlow: () => null,
                backFlow: () => null,
                onMouseEnterResult: (_, { index }) => index,
                onMouseLeaveResult: () => null,
                onArrowUp: () => null,
                onArrowDown: () => null,
            },
        ],
        input: [
            '',
            {
                setInput: (_, { input }) => input,
                activateFlow: () => '',
                backFlow: () => '',
                executeResult: () => '',
            },
        ],
        activeFlow: [
            null as CommandFlow | null,
            {
                activateFlow: (currentFlow, { flow }) =>
                    flow ? { ...flow, scope: flow.scope ?? currentFlow?.scope, previousFlow: currentFlow } : null,
                backFlow: (currentFlow) => currentFlow?.previousFlow ?? null,
            },
        ],
        rawCommandRegistrations: [
            {} as CommandRegistrations,
            {
                registerCommand: (commands, { command }) => {
                    return { ...commands, [command.key]: command }
                },
                deregisterCommand: (commands, { commandKey }) => {
                    const { [commandKey]: _discard, ...cleanedCommands } = commands
                    return cleanedCommands
                },
            },
        ],
    }),
    selectors({
        isUsingCmdKSearch: [
            (selectors) => [selectors.featureFlags],
            (featureFlags) => featureFlags[FEATURE_FLAGS.CMD_K_SEARCH],
        ],
        isSqueak: [
            (selectors) => [selectors.input],
            (input: string) => {
                return input.trim().toLowerCase() === 'squeak'
            },
        ],
        activeResultIndex: [
            (selectors) => [selectors.keyboardResultIndex, selectors.hoverResultIndex],
            (keyboardResultIndex: number, hoverResultIndex: number | null) => {
                return hoverResultIndex ?? keyboardResultIndex
            },
        ],
        commandRegistrations: [
            (selectors) => [
                selectors.rawCommandRegistrations,
                selectors.isUsingCmdKSearch,
                dashboardsModel.selectors.nameSortedDashboards,
                teamLogic.selectors.currentTeam,
            ],
            (
                rawCommandRegistrations: CommandRegistrations,
                isUsingCmdKSearch,
                dashboards: DashboardType[]
            ): CommandRegistrations => {
                if (isUsingCmdKSearch) {
                    // do not add dashboards to commands, as they can be navigated to via search
                    return rawCommandRegistrations
                }

                return {
                    ...rawCommandRegistrations,
                    custom_dashboards: {
                        key: 'custom_dashboards',
                        resolver: dashboards.map((dashboard: DashboardType) => ({
                            key: `dashboard_${dashboard.id}`,
                            icon: IconTableChart,
                            display: `Go to dashboard: ${dashboard.name}`,
                            executor: () => {
                                const { push } = router.actions
                                push(urls.dashboard(dashboard.id))
                            },
                        })),
                        scope: GLOBAL_COMMAND_SCOPE,
                    },
                }
            },
        ],
        regexpCommandPairs: [
            (selectors) => [selectors.commandRegistrations],
            (commandRegistrations: CommandRegistrations) => {
                const array: RegExpCommandPairs = []
                for (const command of Object.values(commandRegistrations)) {
                    if (command.prefixes) {
                        array.push([new RegExp(`^\\s*(${command.prefixes.join('|')})(?:\\s+(.*)|$)`, 'i'), command])
                    } else {
                        array.push([null, command])
                    }
                }
                return array
            },
        ],
        commandSearchResults: [
            (selectors) => [
                selectors.isPaletteShown,
                selectors.regexpCommandPairs,
                selectors.input,
                selectors.activeFlow,
                selectors.isSqueak,
            ],
            (
                isPaletteShown: boolean,
                regexpCommandPairs: RegExpCommandPairs,
                argument: string,
                activeFlow: CommandFlow | null,
                isSqueak: boolean
            ) => {
                if (!isPaletteShown || isSqueak) {
                    return []
                }
                if (activeFlow) {
                    return resolveCommand(activeFlow, argument)
                }
                let directResults: CommandResult[] = []
                let prefixedResults: CommandResult[] = []
                for (const [regexp, command] of regexpCommandPairs) {
                    if (regexp) {
                        const match = argument.match(regexp)
                        if (match && match[1]) {
                            prefixedResults = [...prefixedResults, ...resolveCommand(command, match[2], match[1])]
                        }
                    }
                    directResults = [...directResults, ...resolveCommand(command, argument)]
                }
                const allResults = directResults.concat(prefixedResults)
                let fusableResults: CommandResult[] = []
                let guaranteedResults: CommandResult[] = []
                for (const result of allResults) {
                    if (result.guarantee) {
                        guaranteedResults.push(result)
                    } else {
                        fusableResults.push(result)
                    }
                }
                fusableResults = uniqueBy(fusableResults, (result) => result.display)
                guaranteedResults = uniqueBy(guaranteedResults, (result) => result.display)
                const fusedResults = argument
                    ? new Fuse(fusableResults, {
                          keys: ['display', 'synonyms'],
                      })
                          .search(argument)
                          .slice(0, RESULTS_MAX)
                          .map((result) => result.item)
                    : sample(fusableResults, RESULTS_MAX - guaranteedResults.length)
                return guaranteedResults.concat(fusedResults)
            },
        ],
        commandSearchResultsGrouped: [
            (selectors) => [selectors.commandSearchResults, selectors.activeFlow],
            (commandSearchResults: CommandResult[], activeFlow: CommandFlow | null) => {
                const resultsGrouped: {
                    [scope: string]: CommandResult[]
                } = {}
                if (activeFlow) {
                    resultsGrouped[activeFlow.scope ?? '?'] = []
                }
                for (const result of commandSearchResults) {
                    const scope: string = result.source.scope ?? '?'
                    if (!(scope in resultsGrouped)) {
                        resultsGrouped[scope] = []
                    } // Ensure there's an array to push to
                    resultsGrouped[scope].push({ ...result })
                }
                let rollingGroupIndex = 0
                let rollingResultIndex = 0
                const resultsGroupedInOrder: [string, CommandResultDisplayable[]][] = []
                for (const [group, results] of Object.entries(resultsGrouped)) {
                    resultsGroupedInOrder.push([group, []])
                    for (const result of results) {
                        resultsGroupedInOrder[rollingGroupIndex][1].push({ ...result, index: rollingResultIndex++ })
                    }
                    rollingGroupIndex++
                }
                return resultsGroupedInOrder
            },
        ],
    }),
    listeners(({ actions, values }) => ({
        showPalette: () => {
            posthog.capture('palette shown', { isMobile: isMobile() })
        },
        togglePalette: () => {
            if (values.isPaletteShown) {
                posthog.capture('palette shown', { isMobile: isMobile() })
            }
        },
        executeResult: ({ result }: { result: CommandResult }) => {
            if (result.executor === true) {
                actions.activateFlow(null)
                actions.hidePalette()
            } else {
                const possibleFlow = result.executor?.() || null
                actions.activateFlow(possibleFlow)
                if (!possibleFlow) {
                    actions.hidePalette()
                }
            }
            // Capture command execution, without useless data
            const { icon, index, ...cleanedResult }: Record<string, any> = result
            const { resolver, ...cleanedCommand } = cleanedResult.source
            cleanedResult.source = cleanedCommand
            cleanedResult.isMobile = isMobile()
            posthog.capture('palette command executed', cleanedResult)
        },
        deregisterScope: ({ scope }) => {
            for (const command of Object.values(values.commandRegistrations)) {
                if (command.scope === scope) {
                    actions.deregisterCommand(command.key)
                }
            }
        },
        setInput: async ({ input }, breakpoint) => {
            await breakpoint(300)
            if (input.length > 8) {
                const response = await api.persons.list({ search: input })
                const person = response.results[0]
                if (person) {
                    actions.registerCommand({
                        key: `person-${person.distinct_ids[0]}`,
                        resolver: [
                            {
                                icon: IconPersonFilled,
                                display: `View person ${input}`,
                                executor: () => {
                                    const { push } = router.actions
                                    push(urls.personByDistinctId(person.distinct_ids[0]))
                                },
                            },
                        ],
                        scope: GLOBAL_COMMAND_SCOPE,
                    })
                }
            }
        },
    })),
    events(({ actions, values }) => ({
        afterMount: () => {
            const { push } = actions

            const goTo: Command = {
                key: 'go-to',
                scope: GLOBAL_COMMAND_SCOPE,
                prefixes: ['open', 'visit'],
                resolver: [
                    {
                        icon: IconGauge,
                        display: 'Go to Dashboards',
                        executor: () => {
                            push(urls.dashboards())
                        },
                    },
                    {
                        icon: IconBarChart,
                        display: 'Go to Insights',
                        executor: () => {
                            push(urls.savedInsights())
                        },
                    },
                    {
                        icon: IconTrendingUp,
                        display: 'Go to Trends',
                        executor: () => {
                            // TODO: Don't reset insight on change
                            push(urls.insightNew({ insight: InsightType.TRENDS }))
                        },
                    },
                    {
                        icon: IconFunnelHorizontal,
                        display: 'Go to Funnels',
                        executor: () => {
                            // TODO: Don't reset insight on change
                            push(urls.insightNew({ insight: InsightType.FUNNELS }))
                        },
                    },
                    {
                        icon: IconTrendingFlat,
                        display: 'Go to Retention',
                        executor: () => {
                            // TODO: Don't reset insight on change
                            push(urls.insightNew({ insight: InsightType.RETENTION }))
                        },
                    },
                    {
                        icon: IconEmojiPeople,
                        display: 'Go to Paths',
                        executor: () => {
                            // TODO: Don't reset insight on change
                            push(urls.insightNew({ insight: InsightType.PATHS }))
                        },
                    },
                    {
                        icon: IconLive,
                        display: 'Go to Events',
                        executor: () => {
                            push(urls.events())
                        },
                    },
                    {
                        icon: IconAction,
                        display: 'Go to Actions',
                        executor: () => {
                            push(urls.actions())
                        },
                    },
                    {
                        icon: IconPerson,
                        display: 'Go to Persons',
                        synonyms: ['people'],
                        executor: () => {
                            push(urls.persons())
                        },
                    },
                    {
                        icon: IconCohort,
                        display: 'Go to Cohorts',
                        executor: () => {
                            push(urls.cohorts())
                        },
                    },
                    {
                        icon: IconFlag,
                        display: 'Go to Feature Flags',
                        synonyms: ['feature flags', 'a/b tests'],
                        executor: () => {
                            push(urls.featureFlags())
                        },
                    },
                    {
                        icon: IconComment,
                        display: 'Go to Annotations',
                        executor: () => {
                            push(urls.annotations())
                        },
                    },
                    {
                        icon: IconCorporate,
                        display: 'Go to Team members',
                        synonyms: ['organization', 'members', 'invites', 'teammates'],
                        executor: () => {
                            push(urls.settings('organization'))
                        },
                    },
                    {
                        icon: IconCottage,
                        display: 'Go to project homepage',
                        executor: () => {
                            push(urls.projectHomepage())
                        },
                    },
                    {
                        icon: IconSettings,
                        display: 'Go to Project settings',
                        executor: () => {
                            push(urls.settings('project'))
                        },
                    },
                    {
                        icon: () => (
                            <ProfilePicture name={values.user?.first_name} email={values.user?.email} size="xs" />
                        ),
                        display: 'Go to My settings',
                        synonyms: ['account'],
                        executor: () => {
                            push(urls.settings('user'))
                        },
                    },
                    {
                        icon: IconApps,
                        display: 'Go to Apps',
                        synonyms: ['integrations'],
                        executor: () => {
                            push(urls.projectApps())
                        },
                    },
                    {
                        icon: IconServer,
                        display: 'Go to Instance status & settings',
                        synonyms: ['redis', 'celery', 'django', 'postgres', 'backend', 'service', 'online'],
                        executor: () => {
                            push(urls.instanceStatus())
                        },
                    },
                    {
                        icon: IconLogout,
                        display: 'Log out',
                        executor: () => {
                            userLogic.actions.logout()
                        },
                    },
                ],
            }

            const debugClickhouseQueries: Command = {
                key: 'debug-clickhouse-queries',
                scope: GLOBAL_COMMAND_SCOPE,
                resolver:
                    userLogic.values.user?.is_staff ||
                    userLogic.values.user?.is_impersonated ||
                    preflightLogic.values.preflight?.is_debug ||
                    preflightLogic.values.preflight?.instance_preferences?.debug_queries
                        ? {
                              icon: IconTools,
                              display: 'Debug ClickHouse Queries',
                              executor: () => openCHQueriesDebugModal(),
                          }
                        : [],
            }

            const debugCopySessionRecordingURL: Command = {
                key: 'debug-copy-session-recording-url',
                scope: GLOBAL_COMMAND_SCOPE,
                resolver: {
                    icon: IconRecording,
                    display: 'Debug: Copy the session recording link to clipboard',
                    executor: () => {
                        const url = posthog.get_session_replay_url({ withTimestamp: true, timestampLookBack: 30 })
                        void copyToClipboard(url, 'Current session recording link to clipboard')
                    },
                },
            }

            const calculator: Command = {
                key: 'calculator',
                scope: GLOBAL_COMMAND_SCOPE,
                resolver: (argument) => {
                    // don't try evaluating if there's no argument or if it's a plain number already
                    if (!argument || !isNaN(+argument)) {
                        return null
                    }
                    try {
                        const result = +Parser.evaluate(argument)
                        return isNaN(result)
                            ? null
                            : {
                                  icon: IconCalculate,
                                  display: `= ${result}`,
                                  guarantee: true,
                                  executor: () => {
                                      void copyToClipboard(result.toString(), 'calculation result')
                                  },
                              }
                    } catch {
                        return null
                    }
                },
            }

            const openUrls: Command = {
                key: 'open-urls',
                scope: GLOBAL_COMMAND_SCOPE,
                prefixes: ['open', 'visit'],
                resolver: (argument) => {
                    const results: CommandResultTemplate[] = (teamLogic.values.currentTeam?.app_urls ?? []).map(
                        (url: string) => ({
                            icon: IconOpenInNew,
                            display: `Open ${url}`,
                            synonyms: [`Visit ${url}`],
                            executor: () => {
                                open(url)
                            },
                        })
                    )
                    if (argument && isURL(argument)) {
                        results.push({
                            icon: IconOpenInNew,
                            display: `Open ${argument}`,
                            synonyms: [`Visit ${argument}`],
                            executor: () => {
                                open(argument)
                            },
                        })
                    }
                    results.push({
                        icon: IconOpenInNew,
                        display: 'Open PostHog Docs',
                        synonyms: ['technical documentation'],
                        executor: () => {
                            open('https://posthog.com/docs')
                        },
                    })
                    return results
                },
            }

            const createPersonalApiKey: Command = {
                key: 'create-personal-api-key',
                scope: GLOBAL_COMMAND_SCOPE,
                resolver: {
                    icon: IconLockOpen,
                    display: 'Create Personal API Key',
                    executor: () => ({
                        instruction: 'Give your key a label',
                        icon: IconKeyboard,
                        scope: 'Creating Personal API Key',
                        resolver: (argument) => {
                            if (argument?.length) {
                                return {
                                    icon: IconLockOpen,
                                    display: `Create Key "${argument}"`,
                                    executor: () => {
                                        personalAPIKeysLogic.actions.createKey(argument)
                                        push(urls.settings('user'), {}, 'personal-api-keys')
                                    },
                                }
                            }
                            return null
                        },
                    }),
                },
            }

            const createDashboard: Command = {
                key: 'create-dashboard',
                scope: GLOBAL_COMMAND_SCOPE,
                resolver: {
                    icon: IconGauge,
                    display: 'Create Dashboard',
                    executor: () => ({
                        instruction: 'Name your new dashboard',
                        icon: IconKeyboard,
                        scope: 'Creating Dashboard',
                        resolver: (argument) => {
                            if (argument?.length) {
                                return {
                                    icon: IconGauge,
                                    display: `Create Dashboard "${argument}"`,
                                    executor: () => {
                                        newDashboardLogic.actions.addDashboard({ name: argument })
                                    },
                                }
                            }
                            return null
                        },
                    }),
                },
            }

            const shareFeedback: Command = {
                key: 'share-feedback',
                scope: GLOBAL_COMMAND_SCOPE,
                resolver: {
                    icon: IconComment,
                    display: 'Share Feedback',
                    synonyms: ['send opinion', 'ask question', 'message posthog', 'github issue'],
                    executor: () => ({
                        scope: 'Sharing Feedback',
                        resolver: [
                            {
                                display: 'Send Message Directly to PostHog',
                                icon: IconComment,
                                executor: () => ({
                                    instruction: "What's on your mind?",
                                    icon: IconComment,
                                    resolver: (argument) => ({
                                        icon: IconComment,
                                        display: 'Send',
                                        executor: !argument?.length
                                            ? undefined
                                            : () => {
                                                  posthog.capture('palette feedback', { message: argument })
                                                  return {
                                                      resolver: {
                                                          icon: IconCheckmark,
                                                          display: 'Message Sent!',
                                                          executor: true,
                                                      },
                                                  }
                                              },
                                    }),
                                }),
                            },
                            {
                                icon: IconGithub,
                                display: 'Create GitHub Issue',
                                executor: () => {
                                    open('https://github.com/PostHog/posthog/issues/new/choose')
                                },
                            },
                        ],
                    }),
                },
            }

            actions.registerCommand(goTo)
            actions.registerCommand(openUrls)
            actions.registerCommand(debugClickhouseQueries)
            actions.registerCommand(calculator)
            actions.registerCommand(createPersonalApiKey)
            actions.registerCommand(createDashboard)
            actions.registerCommand(shareFeedback)
            actions.registerCommand(debugCopySessionRecordingURL)
        },
        beforeUnmount: () => {
            actions.deregisterCommand('go-to')
            actions.deregisterCommand('open-urls')
            actions.deregisterCommand('debug-clickhouse-queries')
            actions.deregisterCommand('calculator')
            actions.deregisterCommand('create-personal-api-key')
            actions.deregisterCommand('create-dashboard')
            actions.deregisterCommand('share-feedback')
            actions.deregisterCommand('debug-copy-session-recording-url')
        },
    })),
])
