import { Command, commandLogic, CommandRegistrations } from 'lib/components/CommandPalette/commandLogic'
import { commandLogicType } from 'types/lib/components/CommandPalette/commandLogicType'
import { kea } from 'kea'

export const trendCommandLogic = kea<commandLogicType<Command, CommandRegistrations>>({
    connect: [commandLogic],
    events: () => ({
        afterMount: () => {},
        beforeUnmount: () => {},
    }),
})
