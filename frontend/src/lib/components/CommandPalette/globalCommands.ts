import { Command, CommandResult } from './commandLogic'
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
} from '@ant-design/icons'
import Fuse from 'fuse.js'

type CommandResultKeyed = CommandResult & { key: string }

const COMMAND_GLOBAL_RESULTS: CommandResultKeyed[] = [
    {
        key: 'dashboards',
        icon: FundOutlined,
        display: 'go to dashboards',
        executor: ({ push }) => {
            push('/dashboard')
        },
    },
    {
        key: 'insights',
        icon: RiseOutlined,
        display: 'go to insights',
        executor: ({ push }) => {
            push('/insights')
        },
    },
    {
        key: 'events',
        icon: ContainerOutlined,
        display: 'go to all events',
        executor: ({ push }) => {
            push('/events')
        },
    },
    {
        key: 'actions',
        icon: AimOutlined,
        display: 'go to actions',
        executor: ({ push }) => {
            push('/actions')
        },
    },
    {
        key: 'actions/live',
        icon: SyncOutlined,
        display: 'go to live actions',
        executor: ({ push }) => {
            push('/actions/live')
        },
    },
    {
        key: 'sessions',
        icon: ClockCircleOutlined,
        display: 'go to live sessions',
        executor: ({ push }) => {
            push('/sessions')
        },
    },
    {
        key: 'people',
        icon: UserOutlined,
        display: 'go to persons',
        synonyms: ['people'],
        executor: ({ push }) => {
            push('/people')
        },
    },
    {
        key: 'cohorts',
        icon: UsergroupAddOutlined,
        display: 'go to cohorts',
        executor: ({ push }) => {
            push('/people/cohorts')
        },
    },
    {
        key: 'experiments/feature_flags',
        icon: ExperimentOutlined,
        display: 'go to experiments',
        synonyms: ['feature flags', 'a/b test'],
        executor: ({ push }) => {
            push('/experiments/feature_flags')
        },
    },
    {
        key: 'setup',
        icon: SettingOutlined,
        display: 'go to settings',
        synonyms: ['setup', 'configuration'],
        executor: ({ push }) => {
            push('/setup')
        },
    },
    {
        key: 'annotations',
        icon: MessageOutlined,
        display: 'go to annotations',
        executor: ({ push }) => {
            push('/annotations')
        },
    },
    {
        key: 'team',
        icon: TeamOutlined,
        display: 'go to team',
        executor: ({ push }) => {
            push('/team')
        },
    },
]

const commandGlobalFuse = new Fuse(COMMAND_GLOBAL_RESULTS, { keys: ['display', 'synonyms'] })

const commandGoTo: Command = {
    key: 'go-to',
    prefixes: [],
    resolver: (argument, prefixApplied) => {
        return argument
            ? commandGlobalFuse.search(argument).map((result) => {
                  return { ...result.item, prefixApplied }
              })
            : COMMAND_GLOBAL_RESULTS
    },
}

export const globalCommands: Command[] = [commandGoTo]
