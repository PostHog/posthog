import { Command, commandPaletteLogic, CommandRegistrations } from 'lib/components/CommandPalette/commandPaletteLogic'
import { commandPaletteLogicType } from 'types/lib/components/CommandPalette/commandPaletteLogicType'
import { kea } from 'kea'

export const trendCommandLogic = kea<commandPaletteLogicType<Command, CommandRegistrations>>({
    connect: [commandPaletteLogic],
    events: () => ({
        afterMount: () => {},
        beforeUnmount: () => {},
    }),
})
