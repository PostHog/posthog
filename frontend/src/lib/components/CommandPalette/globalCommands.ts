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
        display: 'go to Dashboards',
        executor: ({ push }) => {
            push('/dashboard')
        },
    },
    {
        key: 'insights',
        icon: RiseOutlined,
        display: 'go to Insights',
        executor: ({ push }) => {
            push('/insights')
        },
    },
    {
        key: 'events',
        icon: ContainerOutlined,
        display: 'go to Events',
        executor: ({ push }) => {
            push('/events')
        },
    },
    {
        key: 'actions',
        icon: AimOutlined,
        display: 'go to Actions',
        executor: ({ push }) => {
            push('/actions')
        },
    },
    {
        key: 'actions/live',
        icon: SyncOutlined,
        display: 'go to Live Actions',
        executor: ({ push }) => {
            push('/actions/live')
        },
    },
    {
        key: 'sessions',
        icon: ClockCircleOutlined,
        display: 'go to Live Sessions',
        executor: ({ push }) => {
            push('/sessions')
        },
    },
    {
        key: 'people',
        icon: UserOutlined,
        display: 'go to People',
        synonyms: ['people'],
        executor: ({ push }) => {
            push('/people')
        },
    },
    {
        key: 'cohorts',
        icon: UsergroupAddOutlined,
        display: 'go to Cohorts',
        executor: ({ push }) => {
            push('/people/cohorts')
        },
    },
    {
        key: 'experiments/feature_flags',
        icon: ExperimentOutlined,
        display: 'go to Experiments',
        synonyms: ['feature flags', 'a/b test'],
        executor: ({ push }) => {
            push('/experiments/feature_flags')
        },
    },
    {
        key: 'setup',
        icon: SettingOutlined,
        display: 'go to Setup',
        synonyms: ['settings', 'configuration'],
        executor: ({ push }) => {
            push('/setup')
        },
    },
    {
        key: 'annotations',
        icon: MessageOutlined,
        display: 'go to Annotations',
        executor: ({ push }) => {
            push('/annotations')
        },
    },
    {
        key: 'team',
        icon: TeamOutlined,
        display: 'go to Team',
        executor: ({ push }) => {
            push('/team')
        },
    },
    {
        key: 'docs',
        icon: BookOutlined,
        display: 'go to documentation',
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
