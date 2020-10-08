import { Command, CommandResultTemplate } from './commandLogic'
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
    BookOutlined,
} from '@ant-design/icons'

const COMMAND_GLOBAL_RESULTS: CommandResultTemplate[] = [
    {
        key: 'dashboards',
        icon: FundOutlined,
        display: 'Go to Dashboards',
        executor: ({ push }) => {
            push('/dashboard')
        },
    },
    {
        key: 'insights',
        icon: RiseOutlined,
        display: 'Go to Insights',
        executor: ({ push }) => {
            push('/insights')
        },
    },
    {
        key: 'events',
        icon: ContainerOutlined,
        display: 'Go to Events',
        executor: ({ push }) => {
            push('/events')
        },
    },
    {
        key: 'actions',
        icon: AimOutlined,
        display: 'Go to Actions',
        executor: ({ push }) => {
            push('/actions')
        },
    },
    {
        key: 'actions/live',
        icon: SyncOutlined,
        display: 'Go to Live Actions',
        executor: ({ push }) => {
            push('/actions/live')
        },
    },
    {
        key: 'sessions',
        icon: ClockCircleOutlined,
        display: 'Go to Live Sessions',
        executor: ({ push }) => {
            push('/sessions')
        },
    },
    {
        key: 'people',
        icon: UserOutlined,
        display: 'Go to People',
        synonyms: ['people'],
        executor: ({ push }) => {
            push('/people')
        },
    },
    {
        key: 'cohorts',
        icon: UsergroupAddOutlined,
        display: 'Go to Cohorts',
        executor: ({ push }) => {
            push('/people/cohorts')
        },
    },
    {
        key: 'experiments/feature_flags',
        icon: ExperimentOutlined,
        display: 'Go to Experiments',
        synonyms: ['feature flags', 'a/b test'],
        executor: ({ push }) => {
            push('/experiments/feature_flags')
        },
    },
    {
        key: 'setup',
        icon: SettingOutlined,
        display: 'Go to Setup',
        synonyms: ['settings', 'configuration'],
        executor: ({ push }) => {
            push('/setup')
        },
    },
    {
        key: 'annotations',
        icon: MessageOutlined,
        display: 'Go to Annotations',
        executor: ({ push }) => {
            push('/annotations')
        },
    },
    {
        key: 'team',
        icon: TeamOutlined,
        display: 'Go to Team',
        executor: ({ push }) => {
            push('/team')
        },
    },
    {
        key: 'docs',
        icon: BookOutlined,
        display: 'Go to Documentation',
        synonyms: ['technical docs'],
        executor: () => {
            window.open('https://posthog.com/docs')
        },
    },
]

const commandGlobal: Command = {
    key: 'global',
    prefixes: [],
    resolver: () => {
        return COMMAND_GLOBAL_RESULTS
    },
}

export const globalCommands: Command[] = [commandGlobal]
