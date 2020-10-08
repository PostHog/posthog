import { Command, CommandResultTemplate, useCommands } from './commandLogic'
import { useActions } from 'kea'
import { router } from 'kea-router'
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
    FunnelPlotOutlined,
    GatewayOutlined,
    InteractionOutlined,
} from '@ant-design/icons'
import { useMemo } from 'react'

export function GlobalCommands(): null {
    const { push } = useActions(router)

    const results: CommandResultTemplate[] = [
        {
            key: 'dashboards',
            icon: FundOutlined,
            display: 'Go to Dashboards',
            executor: () => {
                push('/dashboard')
            },
        },
        {
            key: 'insights',
            icon: RiseOutlined,
            display: 'Go to Insights',
            executor: () => {
                push('/insights')
            },
        },
        {
            key: 'trends',
            icon: RiseOutlined,
            display: 'Go to Trends',
            executor: () => {
                // TODO: Fix me
                push('/insights?insight=TRENDS')
            },
        },
        {
            key: 'sessions',
            icon: ClockCircleOutlined,
            display: 'Go to Sessions',
            executor: () => {
                // TODO: Fix me
                push('/insights?insight=SESSIONS')
            },
        },
        {
            key: 'funnels',
            icon: FunnelPlotOutlined,
            display: 'Go to Funnels',
            executor: () => {
                // TODO: Fix me
                push('/insights?insight=FUNNELS')
            },
        },
        {
            key: 'retention',
            icon: GatewayOutlined,
            display: 'Go to Retention',
            executor: () => {
                // TODO: Fix me
                push('/insights?insight=RETENTION')
            },
        },
        {
            key: 'user_paths',
            icon: InteractionOutlined,
            display: 'Go to User Paths',
            executor: () => {
                // TODO: Fix me
                push('/insights?insight=PATHS')
            },
        },
        {
            key: 'events',
            icon: ContainerOutlined,
            display: 'Go to Events',
            executor: () => {
                push('/events')
            },
        },
        {
            key: 'actions',
            icon: AimOutlined,
            display: 'Go to Actions',
            executor: () => {
                push('/actions')
            },
        },
        {
            key: 'actions/live',
            icon: SyncOutlined,
            display: 'Go to Live Actions',
            executor: () => {
                push('/actions/live')
            },
        },
        {
            key: 'sessions',
            icon: ClockCircleOutlined,
            display: 'Go to Live Sessions',
            executor: () => {
                push('/sessions')
            },
        },
        {
            key: 'people',
            icon: UserOutlined,
            display: 'Go to People',
            synonyms: ['people'],
            executor: () => {
                push('/people')
            },
        },
        {
            key: 'cohorts',
            icon: UsergroupAddOutlined,
            display: 'Go to Cohorts',
            executor: () => {
                push('/people/cohorts')
            },
        },
        {
            key: 'experiments/feature_flags',
            icon: ExperimentOutlined,
            display: 'Go to Experiments',
            synonyms: ['feature flags', 'a/b test'],
            executor: () => {
                push('/experiments/feature_flags')
            },
        },
        {
            key: 'setup',
            icon: SettingOutlined,
            display: 'Go to Setup',
            synonyms: ['settings', 'configuration'],
            executor: () => {
                push('/setup')
            },
        },
        {
            key: 'annotations',
            icon: MessageOutlined,
            display: 'Go to Annotations',
            executor: () => {
                push('/annotations')
            },
        },
        {
            key: 'team',
            icon: TeamOutlined,
            display: 'Go to Team',
            executor: () => {
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

    const globalCommands: Command[] = useMemo(
        () => [
            {
                key: 'global',
                prefixes: [],
                resolver: results,
            },
        ],
        []
    )

    useCommands(globalCommands)

    return null
}
