import { Parser } from 'expr-eval'
import Fuse from 'fuse.js'
import { actions, connect, events, kea, listeners, path, reducers, selectors } from 'kea'
import { router } from 'kea-router'
import posthog from 'posthog-js'

import {
    IconCalculator,
    IconChat,
    IconCheck,
    IconCursor,
    IconDashboard,
    IconDatabase,
    IconDay,
    IconDecisionTree,
    IconExternal,
    IconEye,
    IconFunnels,
    IconGear,
    IconGithub,
    IconGraph,
    IconHogQL,
    IconHome,
    IconKeyboard,
    IconLaptop,
    IconLeave,
    IconLifecycle,
    IconList,
    IconLive,
    IconNight,
    IconNotebook,
    IconPalette,
    IconPeople,
    IconPeopleFilled,
    IconPieChart,
    IconRetention,
    IconRewindPlay,
    IconRocket,
    IconServer,
    IconStickiness,
    IconTestTube,
    IconThoughtBubble,
    IconToggle,
    IconToolbar,
    IconTrends,
    IconUnlock,
    IconUserPaths,
    IconWarning,
    IconX,
} from '@posthog/icons'

import api from 'lib/api'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { IconFlare } from 'lib/lemon-ui/icons'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { isMobile, isURL, uniqueBy } from 'lib/utils'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { newDashboardLogic } from 'scenes/dashboard/newDashboardLogic'
import { INSIGHT_TYPE_URLS } from 'scenes/insights/utils'
import { WATCH_RECORDINGS_OF_KEY, watchRecordingsOfCommand } from 'scenes/session-recordings/replayPaletteCommands'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { SIDE_PANEL_TABS } from '~/layout/navigation-3000/sidepanel/SidePanel'
import { sidePanelLogic } from '~/layout/navigation-3000/sidepanel/sidePanelLogic'
import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { InsightType } from '~/types'

import { commandBarLogic } from '../CommandBar/commandBarLogic'
import { BarStatus } from '../CommandBar/types'
import { hedgehogBuddyLogic } from '../HedgehogBuddy/hedgehogBuddyLogic'
import { openCHQueriesDebugModal } from './DebugCHQueries'
import type { commandPaletteLogicType } from './commandPaletteLogicType'

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

export const GLOBAL_COMMAND_SCOPE = 'global'

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
    connect(() => ({
        actions: [
            router,
            ['push'],
            userLogic,
            ['updateUser'],
            hedgehogBuddyLogic,
            ['setHedgehogModeEnabled'],
            commandBarLogic,
            ['setCommandBar'],
            sidePanelStateLogic,
            ['openSidePanel', 'closeSidePanel'],
        ],
        values: [
            teamLogic,
            ['currentTeam'],
            userLogic,
            ['user'],
            featureFlagLogic,
            ['featureFlags'],
            hedgehogBuddyLogic,
            ['hedgehogModeEnabled'],
            sidePanelLogic,
            ['enabledTabs'],
            sidePanelStateLogic,
            ['sidePanelOpen'],
        ],
        logic: [preflightLogic],
    })),
    actions({
        hidePalette: true,
        showPalette: true,
        togglePalette: true,
        setInput: (input: string) => ({ input }),
        onArrowUp: true,
        onArrowDown: (maxIndex: number) => ({ maxIndex }),
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
        activeResultIndex: [
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
        commandRegistrations: [
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
        isSqueak: [
            (selectors) => [selectors.input],
            (input: string) => {
                return input.trim().toLowerCase() === 'squeak'
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
                            prefixedResults.push(...resolveCommand(command, match[2], match[1]))
                        }
                    }
                    directResults.push(...resolveCommand(command, argument))
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
                    : fusableResults.slice(0, RESULTS_MAX)
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
                                icon: IconPeopleFilled,
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
                        icon: IconDashboard,
                        display: 'Go to Dashboards',
                        executor: () => {
                            push(urls.dashboards())
                        },
                    },
                    {
                        icon: IconHome,
                        display: 'Go to Project homepage',
                        executor: () => {
                            push(urls.projectHomepage())
                        },
                    },
                    {
                        icon: IconGraph,
                        display: 'Go to Insights',
                        executor: () => {
                            push(urls.savedInsights())
                        },
                    },
                    {
                        icon: IconTrends,
                        display: 'Create a new Trend insight',
                        executor: () => {
                            // TODO: Don't reset insight on change
                            push(INSIGHT_TYPE_URLS[InsightType.TRENDS])
                        },
                    },
                    {
                        icon: IconFunnels,
                        display: 'Create a new Funnel insight',
                        executor: () => {
                            // TODO: Don't reset insight on change
                            push(INSIGHT_TYPE_URLS[InsightType.FUNNELS])
                        },
                    },
                    {
                        icon: IconRetention,
                        display: 'Create a new Retention insight',
                        executor: () => {
                            // TODO: Don't reset insight on change
                            push(INSIGHT_TYPE_URLS[InsightType.RETENTION])
                        },
                    },
                    {
                        icon: IconUserPaths,
                        display: 'Create a new Paths insight',
                        executor: () => {
                            // TODO: Don't reset insight on change
                            push(INSIGHT_TYPE_URLS[InsightType.PATHS])
                        },
                    },
                    {
                        icon: IconStickiness,
                        display: 'Create a new Stickiness insight',
                        executor: () => {
                            // TODO: Don't reset insight on change
                            push(INSIGHT_TYPE_URLS[InsightType.STICKINESS])
                        },
                    },
                    {
                        icon: IconLifecycle,
                        display: 'Create a new Lifecycle insight',
                        executor: () => {
                            // TODO: Don't reset insight on change
                            push(INSIGHT_TYPE_URLS[InsightType.LIFECYCLE])
                        },
                    },
                    {
                        icon: IconHogQL,
                        display: 'Create a new SQL insight',
                        synonyms: ['hogql', 'sql'],
                        executor: () => {
                            // TODO: Don't reset insight on change
                            push(INSIGHT_TYPE_URLS[InsightType.SQL])
                        },
                    },
                    {
                        icon: IconNotebook,
                        display: 'Go to Notebooks',
                        executor: () => {
                            push(urls.notebooks())
                        },
                    },
                    {
                        icon: IconLive,
                        display: 'Go to Activity',
                        executor: () => {
                            push(urls.activity())
                        },
                    },
                    {
                        icon: IconDatabase,
                        display: 'Go to Data management',
                        synonyms: ['events'],
                        executor: () => {
                            push(urls.eventDefinitions())
                        },
                    },
                    {
                        icon: IconCursor,
                        display: 'Go to Actions',
                        executor: () => {
                            push(urls.actions())
                        },
                    },
                    {
                        icon: IconList,
                        display: 'Go to Properties',
                        executor: () => {
                            push(urls.propertyDefinitions())
                        },
                    },
                    {
                        icon: IconThoughtBubble,
                        display: 'Go to Annotations',
                        executor: () => {
                            push(urls.annotations())
                        },
                    },
                    {
                        icon: IconPeople,
                        display: 'Go to Persons',
                        synonyms: ['people'],
                        executor: () => {
                            push(urls.persons())
                        },
                    },
                    {
                        icon: IconPeople,
                        display: 'Go to Cohorts',
                        executor: () => {
                            push(urls.cohorts())
                        },
                    },
                    {
                        icon: IconPieChart,
                        display: 'Go to Web analytics',
                        executor: () => {
                            push(urls.webAnalytics())
                        },
                    },
                    {
                        icon: IconServer,
                        display: 'Go to SQL editor',
                        executor: () => {
                            push(urls.sqlEditor())
                        },
                    },
                    {
                        icon: IconWarning,
                        display: 'Go to Error tracking',
                        executor: () => push(urls.errorTracking()),
                    },
                    {
                        display: 'Go to Session replay',
                        icon: IconRewindPlay,
                        executor: () => {
                            push(urls.replay())
                        },
                    },
                    {
                        display: 'Go to Surveys',
                        icon: IconChat,
                        executor: () => {
                            push(urls.surveys())
                        },
                    },
                    {
                        icon: IconToggle,
                        display: 'Go to Feature flags',
                        executor: () => {
                            push(urls.featureFlags())
                        },
                    },
                    {
                        icon: IconTestTube,
                        display: 'Go to Experiments',
                        executor: () => {
                            push(urls.experiments())
                        },
                    },
                    {
                        icon: IconRocket,
                        display: 'Go to Early access features',
                        executor: () => {
                            push(urls.earlyAccessFeatures())
                        },
                    },
                    {
                        icon: IconDecisionTree,
                        display: 'Go to Data pipelines',
                        synonyms: ['integrations'],
                        executor: () => {
                            push(urls.dataPipelines())
                        },
                    },
                    {
                        icon: IconToolbar,
                        display: 'Go to Toolbar',
                        executor: () => {
                            push(urls.toolbarLaunch())
                        },
                    },
                    {
                        icon: IconGear,
                        display: 'Go to Project settings',
                        executor: () => {
                            push(urls.settings('project'))
                        },
                    },
                    {
                        icon: IconGear,
                        display: 'Go to Organization settings',
                        executor: () => {
                            push(urls.settings('organization'))
                        },
                    },
                    {
                        icon: () => <ProfilePicture user={values.user} size="xs" />,
                        display: 'Go to User settings',
                        synonyms: ['account', 'profile'],
                        executor: () => {
                            push(urls.settings('user'))
                        },
                    },
                    {
                        icon: IconLeave,
                        display: 'Log out',
                        executor: () => {
                            userLogic.actions.logout()
                        },
                    },
                    {
                        icon: IconUnlock,
                        display: 'Go to Personal API Keys',
                        executor: () => {
                            push(urls.settings('user-api-keys'))
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
                              icon: IconDatabase,
                              display: 'Debug ClickHouse queries',
                              executor: () => openCHQueriesDebugModal(),
                          }
                        : [],
            }

            const debugCopySessionRecordingURL: Command = {
                key: 'debug-copy-session-recording-url',
                scope: GLOBAL_COMMAND_SCOPE,
                resolver: {
                    icon: IconRewindPlay,
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
                                  icon: IconCalculator,
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
                    const words = argument?.split(' ')
                    const url = words?.find((word) => isURL(word))
                    if (url) {
                        return {
                            icon: IconExternal,
                            display: `Open ${url}`,
                            synonyms: [`Visit ${url}`],
                            executor: () => {
                                open(url)
                            },
                        }
                    }

                    if (words && words.length > 0 && ['open', 'visit'].includes(words[0].toLowerCase())) {
                        const results: CommandResultTemplate[] = (teamLogic.values.currentTeam?.app_urls ?? []).map(
                            (url: string) => ({
                                icon: IconExternal,
                                display: `Open ${url}`,
                                synonyms: [`Visit ${url}`],
                                executor: () => {
                                    open(url)
                                },
                            })
                        )
                        results.push({
                            icon: IconExternal,
                            display: 'Open PostHog Docs',
                            synonyms: ['technical documentation'],
                            executor: () => {
                                open('https://posthog.com/docs')
                            },
                        })
                        return results
                    }

                    return null
                },
            }

            const createDashboard: Command = {
                key: 'create-dashboard',
                scope: GLOBAL_COMMAND_SCOPE,
                resolver: {
                    icon: IconDashboard,
                    display: 'Create Dashboard',
                    executor: () => ({
                        instruction: 'Name your new dashboard',
                        icon: IconKeyboard,
                        scope: 'Creating Dashboard',
                        resolver: (argument) => {
                            if (argument?.length) {
                                return {
                                    icon: IconDashboard,
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
                    icon: IconThoughtBubble,
                    display: 'Share Feedback',
                    synonyms: ['send opinion', 'ask question', 'message posthog', 'github issue'],
                    executor: () => ({
                        scope: 'Sharing Feedback',
                        resolver: [
                            {
                                display: 'Send Message Directly to PostHog',
                                icon: IconThoughtBubble,
                                executor: () => ({
                                    instruction: "What's on your mind?",
                                    icon: IconThoughtBubble,
                                    resolver: (argument) => ({
                                        icon: IconThoughtBubble,
                                        display: 'Send',
                                        executor: !argument?.length
                                            ? undefined
                                            : () => {
                                                  posthog.capture('palette feedback', { message: argument })
                                                  return {
                                                      resolver: {
                                                          icon: IconCheck,
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

            const toggleTheme: Command = {
                key: 'toggle-theme',
                scope: GLOBAL_COMMAND_SCOPE,
                resolver: {
                    icon: IconEye,
                    display: 'Change theme',
                    synonyms: ['toggle theme', 'dark mode', 'light mode'],
                    executor: () => ({
                        scope: 'Change theme',
                        resolver: [
                            {
                                icon: IconDay,
                                display: 'Light mode',
                                executor: () => {
                                    actions.updateUser({ theme_mode: 'light' })
                                },
                            },
                            {
                                icon: IconNight,
                                display: 'Dark mode',
                                executor: () => {
                                    actions.updateUser({ theme_mode: 'dark' })
                                },
                            },
                            {
                                icon: IconLaptop,
                                display: 'Sync with system preferences',
                                executor: () => {
                                    actions.updateUser({ theme_mode: 'system' })
                                },
                            },
                            {
                                icon: IconPalette,
                                display: 'Add custom CSS',
                                executor: () => push(urls.customCss()),
                            },
                        ],
                    }),
                },
            }

            const toggleHedgehogMode: Command = {
                key: 'toggle-hedgehog-mode',
                scope: GLOBAL_COMMAND_SCOPE,
                resolver: {
                    icon: IconFlare,
                    display: `${values.hedgehogModeEnabled ? 'Disable' : 'Enable'} hedgehog mode`,
                    synonyms: ['buddy', 'toggle', 'max'],
                    executor: () => {
                        actions.setHedgehogModeEnabled(!values.hedgehogModeEnabled)
                    },
                },
            }

            const shortcuts: Command = {
                key: 'shortcuts',
                scope: GLOBAL_COMMAND_SCOPE,
                resolver: {
                    icon: IconKeyboard,
                    display: 'Open keyboard shortcut overview',
                    executor: () => {
                        actions.setCommandBar(BarStatus.SHOW_SHORTCUTS)

                        // :HACKY: we need to return a dummy flow here, as otherwise
                        // the executor will hide the command bar, which also displays
                        // the shortcut overview
                        const dummyFlow: CommandFlow = {
                            resolver: () => ({
                                icon: <></>,
                                display: '',
                                executor: true,
                            }),
                        }
                        return dummyFlow
                    },
                },
            }

            const sidepanel: Command = {
                key: 'sidepanel',
                scope: GLOBAL_COMMAND_SCOPE,
                resolver: [
                    ...values.enabledTabs.map((tab) => {
                        const { Icon, label } = SIDE_PANEL_TABS[tab]
                        return {
                            icon: Icon,
                            display: `Open ${label} side panel`,
                            executor: () => {
                                actions.openSidePanel(tab)
                            },
                        }
                    }),
                    ...(values.sidePanelOpen
                        ? [
                              {
                                  icon: IconX,
                                  display: 'Close side panel',
                                  executor: () => {
                                      actions.closeSidePanel()
                                  },
                              },
                          ]
                        : []),
                ],
            }

            actions.registerCommand(goTo)
            actions.registerCommand(openUrls)
            actions.registerCommand(debugClickhouseQueries)
            actions.registerCommand(calculator)
            actions.registerCommand(createDashboard)
            actions.registerCommand(shareFeedback)
            actions.registerCommand(debugCopySessionRecordingURL)
            actions.registerCommand(toggleTheme)
            actions.registerCommand(toggleHedgehogMode)
            actions.registerCommand(shortcuts)
            actions.registerCommand(sidepanel)
            actions.registerCommand(watchRecordingsOfCommand(push))
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
            actions.deregisterCommand('toggle-theme')
            actions.deregisterCommand('toggle-hedgehog-mode')
            actions.deregisterCommand('shortcuts')
            actions.deregisterCommand('sidepanel')
            actions.deregisterCommand(WATCH_RECORDINGS_OF_KEY)
        },
    })),
])
