import { InsertCommand } from './editorTypes'
import { buildInsertCommands } from './InsertMenu'
import { getMarkdownNotebookDefaultRegistry } from './registry'

describe('buildInsertCommands', () => {
    const noop = (): void => {}

    const build = (
        openSavedInsightPicker?: (nodeId: string) => void
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
            openSavedInsightPicker
        )
        return { commands, replaceNodeWithInsertedComponent }
    }

    const getSavedInsightCommand = (commands: InsertCommand[]): InsertCommand | undefined =>
        commands.find((candidate) => candidate.key === 'query-saved-insight')

    it('opens the picker when one is provided instead of inserting a node', () => {
        const openSavedInsightPicker = jest.fn()
        const { commands, replaceNodeWithInsertedComponent } = build(openSavedInsightPicker)
        const command = getSavedInsightCommand(commands)
        command?.run('node-1')

        expect(command).not.toBeUndefined()
        expect(openSavedInsightPicker).toHaveBeenCalledWith('node-1')
        expect(replaceNodeWithInsertedComponent).not.toHaveBeenCalled()
    })

    it('omits the saved-insight command entirely when no picker is provided', () => {
        const { commands } = build()
        expect(getSavedInsightCommand(commands)).toBeUndefined()
    })
})
