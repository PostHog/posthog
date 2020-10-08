import { Command, CommandResult } from './commandLogic'
import { LineChartOutlined } from '@ant-design/icons'
import Fuse from 'fuse.js'

type CommandResultKeyed = CommandResult & { key: string }

const COMMAND_GO_TO_RESULTS: CommandResultKeyed[] = [
    {
        key: 'insights',
        icon: LineChartOutlined,
        text: 'go to insights page',
        executor: ({ push }) => {
            push('/insights')
        },
    },
    {
        key: 'people',
        icon: LineChartOutlined,
        text: 'go to people page',
        executor: ({ push }) => {
            push('/people')
        },
    },
    {
        key: 'setup',
        icon: LineChartOutlined,
        text: 'go to setup page',
        executor: ({ push }) => {
            push('/setup')
        },
    },
    {
        key: 'events',
        icon: LineChartOutlined,
        text: 'go to events page',
        executor: ({ push }) => {
            push('/events')
        },
    },
    {
        key: 'feature flags',
        icon: LineChartOutlined,
        text: 'go to feature flags page',
        executor: ({ push }) => {
            push('/experiments/feature_flags')
        },
    },
]

const commandGoToFuse = new Fuse(COMMAND_GO_TO_RESULTS, { keys: ['key'] })

const commandGoTo: Command = {
    key: 'go-to',
    prefixes: ['go to', '/d'],
    resolver: (argument, prefixApplied) => {
        return argument
            ? commandGoToFuse.search(argument).map((result) => {
                  return { ...result.item, prefixApplied }
              })
            : COMMAND_GO_TO_RESULTS
    },
}

export const globalCommands: Command[] = [commandGoTo]
