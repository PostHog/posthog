import { kea } from 'kea'
import { router } from 'kea-router'
import { commandLogicType } from 'types/lib/components/CommandPalette/commandLogicType'
import Fuse from 'fuse.js'
import { dashboardsModel } from '~/models/dashboardsModel'

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
    custom_command?: boolean
}

export type CommandResult = CommandResultTemplate & {
    command: Command
    index?: number
}

export type CommandResolver = (argument?: string, prefixApplied?: string) => CommandResultTemplate[]

export interface Command {
    key: string // Unique command identification key
    prefixes?: string[] // Command prefixes, e.g. "go to". Prefix-less case is dynamic base command (e.g. Dashboard)
    resolver: CommandResolver | CommandResultTemplate[] // Resolver based on arguments (prefix excluded)
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
    resultsArray: CommandResult[],
    argument?: string,
    prefixApplied?: string
): void {
    const results = Array.isArray(command.resolver) ? command.resolver : command.resolver(argument, prefixApplied)
    resultsArray.push(
        ...results.map((result) => {
            return { ...result, command } as CommandResult
        })
    )
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
            window.posthog.capture('palette shown')
        },
        togglePalette: () => {
            if (values.isPaletteShown) window.posthog.capture('palette shown')
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
            if (/^[a-zA-Z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-zA-Z0-9-]+(?:\.[a-zA-Z0-9-]+)*$/.test(input)) {
                const response = await api.get('api/person/?email=' + input)
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
            } else if (input.length > 10) {
                const response = await api.get('api/person/?distinct_id=' + input)
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
                const fuse = new Fuse(directResults.concat(prefixedResults), {
                    keys: ['display', 'synonyms'],
                })
                return fuse
                    .search(argument)
                    .slice(0, RESULTS_MAX)
                    .map((result) => result.item)
                    .sort((result) => (result.command.scope === GLOBAL_COMMAND_SCOPE ? 1 : -1))
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
