import { Command, CommandResult } from './commandLogic'
import { LineChartOutlined } from '@ant-design/icons'
import Fuse from 'fuse.js'

type CommandResultKeyed = CommandResult & { key: string }

const COMMAND_GO_TO_RESULTS: CommandResultKeyed[] = [
    {
        key: 'insights',
        icon: LineChartOutlined,
        text: 'Insights page',
        executor: ({ pushUrl }) => {
            pushUrl('/insights')
        },
    },
    {
        key: 'people',
        icon: LineChartOutlined,
        text: 'People page',
        executor: ({ pushUrl }) => {
            pushUrl('/people')
        },
    },
    {
        key: 'setup',
        icon: LineChartOutlined,
        text: 'Setup page',
        executor: ({ pushUrl }) => {
            pushUrl('/setup')
        },
    },
    {
        key: 'events',
        icon: LineChartOutlined,
        text: 'Events page',
        executor: ({ pushUrl }) => {
            pushUrl('/events')
        },
    },
    {
        key: 'feature flags',
        icon: LineChartOutlined,
        text: 'Feature Flags page',
        executor: ({ pushUrl }) => {
            pushUrl('/experiments/feature_flags')
        },
    },
]

const commandGoToFuse = new Fuse(COMMAND_GO_TO_RESULTS, { keys: ['name'] })

const commandGoTo: Command = {
    prefixes: ['go to', '/d'],
    resolver: (argument) => {
        return commandGoToFuse.search(argument).map((result) => result.item)
    },
}

export const commands: Command[] = [commandGoTo]
