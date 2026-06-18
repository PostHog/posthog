import { InsertCommand } from './editorTypes'
import { buildInsertCommands } from './InsertMenu'
import { getMarkdownNotebookDefaultRegistry } from './registry'
import { NotebookComponentBlockNode } from './types'

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

    const getSavedInsightCommand = (commands: InsertCommand[]): InsertCommand => {
        const command = commands.find((candidate) => candidate.key === 'query-saved-insight')
        if (!command) {
            throw new Error('saved-insight command missing')
        }
        return command
    }

    it('opens the picker when one is provided instead of inserting an empty node', () => {
        const openSavedInsightPicker = jest.fn()
        const { commands, replaceNodeWithInsertedComponent } = build(openSavedInsightPicker)
        getSavedInsightCommand(commands).run('node-1')

        expect(openSavedInsightPicker).toHaveBeenCalledWith('node-1')
        expect(replaceNodeWithInsertedComponent).not.toHaveBeenCalled()
    })

    it('falls back to inserting an empty saved-insight node when no picker is provided', () => {
        const { commands, replaceNodeWithInsertedComponent } = build()
        getSavedInsightCommand(commands).run('node-1')

        expect(replaceNodeWithInsertedComponent).toHaveBeenCalledTimes(1)
        const [, insertedNode] = replaceNodeWithInsertedComponent.mock.calls[0] as [string, NotebookComponentBlockNode]
        expect(insertedNode.tagName).toBe('Query')
        expect(insertedNode.props.query).toEqual({ kind: 'SavedInsightNode', shortId: '' })
    })
})
