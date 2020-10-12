import { kea } from 'kea'
import { router } from 'kea-router'
import { commandLogicType } from 'types/lib/components/CommandPalette/commandLogicType'
import Fuse from 'fuse.js'
import { dashboardsModel } from '~/models/dashboardsModel'
import { Parser } from 'expr-eval'
import _ from 'lodash'
import {
    FundOutlined,
    RiseOutlined,
    ContainerOutlined,
    AimOutlined,
    SyncOutlined,
    ClockCircleOutlined,
    UserOutlined,
    UsergroupAddOutlined,
    ExperimentOutlined,
    SettingOutlined,
    MessageOutlined,
    TeamOutlined,
    LinkOutlined,
    CalculatorOutlined,
    FunnelPlotOutlined,
    GatewayOutlined,
    InteractionOutlined,
    HeartOutlined,
    LogoutOutlined,
    PlusOutlined,
    LineChartOutlined,
    KeyOutlined,
} from '@ant-design/icons'
import { DashboardType } from '~/types'
import api from 'lib/api'
import { appUrlsLogic } from '../AppEditorLink/appUrlsLogic'
import { isURL } from 'lib/utils'

export type CommandExecutor = () => void

export interface CommandResultTemplate {
    icon: any // any, because Ant Design icons are some weird ForwardRefExoticComponent type
    display: string
    synonyms?: string[]
    prefixApplied?: string
    executor: CommandExecutor
    guarantee?: boolean // show result always and first, regardless of fuzzy search
    custom_command?: boolean
}

export type CommandResult = CommandResultTemplate & {
    command: Command
    index?: number
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

export type CommandRegistrations = {
    [commandKey: string]: Command
}

export type RegExpCommandPairs = [RegExp | null, Command][]

const RESULTS_MAX = 5

const GLOBAL_COMMAND_SCOPE = 'global'

function resolveCommand(
    command: Command,
    resultsSoFar: CommandResult[],
    argument?: string,
    prefixApplied?: string
): void {
    let results = command.resolver instanceof Function ? command.resolver(argument, prefixApplied) : command.resolver // run resolver or use ready-made results
    if (!results) return // skip if no result
    if (!Array.isArray(results)) results = [results] // work with a single result and with an array of results
    const resultsWithCommand: CommandResult[] = results.map((result) => {
        return { ...result, command }
    })
    resultsSoFar.push(...resultsWithCommand)
}

export const commandLogic = kea<commandLogicType<Command, CommandRegistrations>>({
    connect: () => ({
        values: [appUrlsLogic, ['appUrls', 'suggestions']],
    }),
    actions: {
        hidePalette: true,
        showPalette: true,
        togglePalette: true,
        setSearchInput: (input: string) => ({ input }),
        registerCommand: (command: Command) => ({ command }),
        deregisterCommand: (commandKey: string) => ({ commandKey }),
        setCustomCommand: (commandKey: string) => ({ commandKey }),
        deregisterAllWithMatch: (keyPrefix: string) => ({ keyPrefix }),
    },
    reducers: {
        isPaletteShown: [
            false,
            {
                hidePalette: () => false,
                showPalette: () => true,
                togglePalette: (previousState) => !previousState,
            },
        ],
        rawCommandRegistrations: [
            {} as CommandRegistrations,
            {
                registerCommand: (commands, { command }) => {
                    return { ...commands, [command.key]: command }
                },
                deregisterCommand: (commands, { commandKey }) => {
                    const cleanedCommands = { ...commands }
                    delete cleanedCommands[commandKey]
                    return cleanedCommands
                },
            },
        ],
        searchInput: [
            '',
            {
                setSearchInput: (_, { input }) => input,
            },
        ],
        customCommand: [
            '',
            {
                setCustomCommand: (_, { commandKey }) => commandKey,
            },
        ],
    },
    listeners: ({ actions, values }) => ({
        showPalette: () => {
            window.posthog?.capture('palette shown')
        },
        togglePalette: () => {
            if (values.isPaletteShown) window.posthog?.capture('palette shown')
        },
        deregisterAllWithMatch: ({ keyPrefix }) => {
            for (const command of Object.values(values.commandRegistrations)) {
                if (command.key.includes(keyPrefix) || command.scope.includes(keyPrefix)) {
                    actions.deregisterCommand(command.key)
                }
            }
        },
        setSearchInput: async ({ input }, breakpoint) => {
            await breakpoint(500)
            actions.deregisterAllWithMatch('person')
            if (input.length > 8) {
                const response = await api.get('api/person/?key_identifier=' + input)
                const person = response.results[0]
                if (person) {
                    actions.registerCommand({
                        key: `person-${person.distinct_ids[0]}`,
                        prefixes: [],
                        resolver: [
                            {
                                icon: UserOutlined,
                                display: `View person ${input}`,
                                executor: () => {
                                    const { push } = router.actions
                                    push(`/person/${person.distinct_ids[0]}`)
                                },
                            },
                        ],
                        scope: GLOBAL_COMMAND_SCOPE,
                    })
                }
            }
        },
    }),
    selectors: {
        isSqueak: [
            (selectors) => [selectors.searchInput],
            (searchInput: string) => {
                return searchInput.trim().toLowerCase() === 'squeak'
            },
        ],
        commandRegistrations: [
            (s) => [
                s.rawCommandRegistrations,
                dashboardsModel.selectors.dashboards,
                appUrlsLogic({ actionId: null }).selectors.appUrls,
                appUrlsLogic({ actionId: null }).selectors.suggestions,
            ],
            (rawCommandRegistrations, dashboards) => ({
                ...rawCommandRegistrations,
                custom_dashboards: {
                    key: 'custom_dashboards',
                    prefixes: [],
                    resolver: dashboards.map((dashboard: DashboardType) => ({
                        key: `dashboard_${dashboard.id}`,
                        icon: LineChartOutlined,
                        display: `Go to Custom Dashboard ${dashboard.name}`,
                        executor: () => {
                            const { push } = router.actions
                            push(`/dashboard/${dashboard.id}`)
                        },
                    })),
                    scope: GLOBAL_COMMAND_SCOPE,
                },
            }),
        ],
        regexpCommandPairs: [
            (selectors) => [selectors.commandRegistrations],
            (commandRegistrations: CommandRegistrations) => {
                const array: RegExpCommandPairs = []
                for (const command of Object.values(commandRegistrations)) {
                    if (command.prefixes)
                        array.push([new RegExp(`^\\s*(${command.prefixes.join('|')})(?:\\s+(.*)|$)`, 'i'), command])
                    else array.push([null, command])
                }
                return array
            },
        ],
        commandSearchResults: [
            (selectors) => [selectors.regexpCommandPairs, selectors.searchInput, selectors.isSqueak],
            (regexpCommandPairs: RegExpCommandPairs, argument: string, isSqueak: boolean) => {
                if (isSqueak) return []
                const directResults: CommandResult[] = []
                const prefixedResults: CommandResult[] = []
                for (const [regexp, command] of regexpCommandPairs) {
                    if (regexp) {
                        const match = argument.match(regexp)
                        if (match && match[1]) {
                            resolveCommand(command, prefixedResults, match[2], match[1])
                        }
                    }
                    resolveCommand(command, directResults, argument)
                }
                const allResults = directResults.concat(prefixedResults)
                const fusableResults: CommandResult[] = []
                const guaranteedResults: CommandResult[] = []
                for (const result of allResults) {
                    if (result.guarantee) guaranteedResults.push(result)
                    else fusableResults.push(result)
                }
                const fusedResults = argument
                    ? new Fuse(fusableResults, {
                          keys: ['display', 'synonyms'],
                      })
                          .search(argument)
                          .slice(0, RESULTS_MAX)
                          .map((result) => result.item)
                    : _.sampleSize(fusableResults, RESULTS_MAX - guaranteedResults.length)
                const finalResults = guaranteedResults.concat(fusedResults)
                // put global scope lasst
                return finalResults.sort((result) => (result.command.scope === GLOBAL_COMMAND_SCOPE ? 1 : -1))
            },
        ],
        commandSearchResultsGrouped: [
            (selectors) => [selectors.commandSearchResults],
            (commandSearchResults: CommandResult[]) => {
                const resultsGrouped: { [scope: string]: CommandResult[] } = {}
                for (const result of commandSearchResults) {
                    const scope: string = result.command.scope
                    if (!(scope in resultsGrouped)) resultsGrouped[scope] = [] // Ensure there's an array to push to
                    resultsGrouped[scope].push({ ...result })
                }
                let rollingIndex = 0
                const resultsGroupedInOrder = Object.entries(resultsGrouped)
                for (const [, group] of resultsGroupedInOrder) {
                    for (const result of group) {
                        result.index = rollingIndex++
                    }
                }
                return resultsGroupedInOrder
            },
        ],
    },

    events: ({ actions, values }) => ({
        afterMount: () => {
            const { push } = router.actions
            const results: CommandResultTemplate[] = [
                {
                    icon: FundOutlined,
                    display: 'Go to Dashboards',
                    executor: () => {
                        push('/dashboard')
                    },
                },
                {
                    icon: RiseOutlined,
                    display: 'Go to Insights',
                    executor: () => {
                        push('/insights')
                    },
                },
                {
                    icon: RiseOutlined,
                    display: 'Go to Trends',
                    executor: () => {
                        // TODO: Fix me
                        push('/insights?insight=TRENDS')
                    },
                },
                {
                    icon: ClockCircleOutlined,
                    display: 'Go to Sessions',
                    executor: () => {
                        // TODO: Fix me
                        push('/insights?insight=SESSIONS')
                    },
                },
                {
                    icon: FunnelPlotOutlined,
                    display: 'Go to Funnels',
                    executor: () => {
                        // TODO: Fix me
                        push('/insights?insight=FUNNELS')
                    },
                },
                {
                    icon: GatewayOutlined,
                    display: 'Go to Retention',
                    executor: () => {
                        // TODO: Fix me
                        push('/insights?insight=RETENTION')
                    },
                },
                {
                    icon: InteractionOutlined,
                    display: 'Go to User Paths',
                    executor: () => {
                        // TODO: Fix me
                        push('/insights?insight=PATHS')
                    },
                },
                {
                    icon: ContainerOutlined,
                    display: 'Go to Events',
                    executor: () => {
                        push('/events')
                    },
                },
                {
                    icon: AimOutlined,
                    display: 'Go to Actions',
                    executor: () => {
                        push('/actions')
                    },
                },
                {
                    icon: SyncOutlined,
                    display: 'Go to Live Actions',
                    executor: () => {
                        push('/actions/live')
                    },
                },
                {
                    icon: ClockCircleOutlined,
                    display: 'Go to Live Sessions',
                    executor: () => {
                        push('/sessions')
                    },
                },
                {
                    icon: UserOutlined,
                    display: 'Go to People',
                    synonyms: ['people'],
                    executor: () => {
                        push('/people')
                    },
                },
                {
                    icon: UsergroupAddOutlined,
                    display: 'Go to Cohorts',
                    executor: () => {
                        push('/people/cohorts')
                    },
                },
                {
                    icon: ExperimentOutlined,
                    display: 'Go to Experiments',
                    synonyms: ['feature flags', 'a/b tests'],
                    executor: () => {
                        push('/experiments/feature_flags')
                    },
                },
                {
                    icon: SettingOutlined,
                    display: 'Go to Setup',
                    synonyms: ['settings', 'configuration'],
                    executor: () => {
                        push('/setup')
                    },
                },
                {
                    icon: MessageOutlined,
                    display: 'Go to Annotations',
                    executor: () => {
                        push('/annotations')
                    },
                },
                {
                    icon: TeamOutlined,
                    display: 'Go to Team',
                    executor: () => {
                        push('/team')
                    },
                },
                {
                    icon: LinkOutlined,
                    display: 'Open PostHog Docs',
                    synonyms: ['technical documentation'],
                    executor: () => {
                        open('https://posthog.com/docs')
                    },
                },
                {
                    icon: HeartOutlined,
                    display: 'Share Feedback',
                    synonyms: ['help', 'support'],
                    executor: () => {
                        open('mailto:hey@posthog.com?subject=PostHog%20feedback%20(command)')
                    },
                },
                {
                    icon: PlusOutlined,
                    display: 'Create Action',
                    executor: () => {
                        push('/action')
                    },
                },
                {
                    icon: LogoutOutlined,
                    display: 'Log Out',
                    executor: () => {
                        window.location.href = '/logout'
                    },
                },
                {
                    icon: KeyOutlined,
                    display: 'Create a Personal API Key',
                    custom_command: true,
                    executor: () => {
                        actions.setCustomCommand('create_api_key')
                    },
                },
            ]

            const globalCommands: Command[] = [
                {
                    key: 'global-commands',
                    scope: GLOBAL_COMMAND_SCOPE,
                    prefixes: ['open', 'visit'],
                    resolver: results,
                },
                {
                    key: 'calculator',
                    scope: GLOBAL_COMMAND_SCOPE,
                    prefixes: [],
                    resolver: (argument) => {
                        // don't try evaluating if there's no argument or if it's a plain number already
                        if (!argument || !isNaN(+argument)) return null
                        try {
                            const result = +Parser.evaluate(argument)
                            return isNaN(result)
                                ? null
                                : {
                                      icon: CalculatorOutlined,
                                      display: `= ${Parser.evaluate(argument)}`,
                                      guarantee: true,
                                      executor: () => {
                                          open(`https://www.wolframalpha.com/input/?i=${encodeURIComponent(argument)}`)
                                      },
                                  }
                        } catch {
                            return null
                        }
                    },
                },
                {
                    key: 'open-urls',
                    scope: GLOBAL_COMMAND_SCOPE,
                    prefixes: [],
                    resolver: (argument) => {
                        const results: CommandResultTemplate[] = (values.appUrls ?? [])
                            .concat(values.suggestedUrls ?? [])
                            .map((url: string) => ({
                                icon: LinkOutlined,
                                display: `Open ${url}`,
                                synonyms: [`Visit ${url}`],
                                executor: () => {
                                    open(url)
                                },
                            }))
                        if (isURL(argument))
                            results.push({
                                icon: LinkOutlined,
                                display: `Open ${argument}`,
                                synonyms: [`Visit ${argument}`],
                                executor: () => {
                                    open(argument)
                                },
                            })
                        return results
                    },
                },
            ]
            for (const command of globalCommands) {
                actions.registerCommand(command)
            }
        },
        beforeUnmount: () => {
            actions.deregisterCommand('global-commands')
            actions.deregisterCommand('open-urls')
        },
    }),
})
