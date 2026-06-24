import { InsertCommand } from './editorTypes'
import { buildInsertCommands } from './InsertMenu'
import { getMarkdownNotebookDefaultRegistry } from './registry'

describe('buildInsertCommands', () => {
    const noop = (): void => {}

    const build = (
        extraCommands?: InsertCommand[]
    ): { commands: InsertCommand[]; replaceNodeWithInsertedComponent: jest.Mock } => {
        const replaceNodeWithInsertedComponent = jest.fn()
        const commands = buildInsertCommands(
            getMarkdownNotebookDefaultRegistry(),
            replaceNodeWithInsertedComponent,
            noop,
            noop,
            noop,
            noop,
            undefined,
            undefined,
            extraCommands
        )
        return { commands, replaceNodeWithInsertedComponent }
    }

    it('appends caller-supplied commands and runs their callbacks untouched', () => {
        const run = jest.fn()
        const extraCommand: InsertCommand = { key: 'custom', label: 'Custom', category: 'Insight', run }
        const { commands, replaceNodeWithInsertedComponent } = build([extraCommand])

        const command = commands.find((candidate) => candidate.key === 'custom')
        command?.run('node-1')

        expect(command).toBe(extraCommand)
        expect(run).toHaveBeenCalledWith('node-1')
        expect(replaceNodeWithInsertedComponent).not.toHaveBeenCalled()
    })

    it('omits caller-supplied commands when none are provided', () => {
        const { commands } = build()
        expect(commands.find((candidate) => candidate.key === 'custom')).toBeUndefined()
    })
})
