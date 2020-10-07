import { Command, CommandResult } from './commandLogic'
import { LineChartOutlined } from '@ant-design/icons'
import Fuse from 'fuse.js'

type CommandResultKeyed = CommandResult & { key: string }

const COMMAND_GO_TO_RESULTS: CommandResultKeyed[] = [
    {
        key: 'insights',
        icon: LineChartOutlined,
        text: 'Insights page',
        executor: ({ push }) => {
            push('/insights')
        },
    },
    {
        key: 'people',
        icon: LineChartOutlined,
        text: 'People page',
        executor: ({ push }) => {
            push('/people')
        },
    },
    {
        key: 'setup',
        icon: LineChartOutlined,
        text: 'Setup page',
        executor: ({ push }) => {
            push('/setup')
        },
    },
    {
        key: 'events',
        icon: LineChartOutlined,
        text: 'Events page',
        executor: ({ push }) => {
            push('/events')
        },
    },
    {
        key: 'feature flags',
        icon: LineChartOutlined,
        text: 'Feature Flags page',
        executor: ({ push }) => {
            push('/experiments/feature_flags')
        },
    },
]

const commandGoToFuse = new Fuse(COMMAND_GO_TO_RESULTS, { keys: ['key'] })

const commandGoTo: Command = {
    key: 'go-to',
    prefixes: ['go to', '/d'],
    resolver: (argument) => {
        return argument ? commandGoToFuse.search(argument).map((result) => result.item) : COMMAND_GO_TO_RESULTS
    },
}

export const globalCommands: Command[] = [commandGoTo]
