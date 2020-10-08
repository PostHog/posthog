import { Command, CommandResult } from './commandLogic'
import { LineChartOutlined } from '@ant-design/icons'
import Fuse from 'fuse.js'

const COMMAND_GLOBAL_RESULTS: CommandResult[] = [
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
        key: 'feature_flags',
        icon: LineChartOutlined,
        text: 'go to feature flags page',
        executor: ({ push }) => {
            push('/experiments/feature_flags')
        },
    },
]

const commandGlobalFuse = new Fuse(COMMAND_GLOBAL_RESULTS, { keys: ['key'] })

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
