import { InsertCommand } from './editorTypes'
import { buildInsertCommands, groupInsertCommandsByCategory } from './InsertMenu'
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

    it('offers every insight type under the Insight category', () => {
        const { commands } = build()
        const insightLabels = commands
            .filter((command) => command.category === 'Insight')
            .map((command) => command.label)

        expect(insightLabels).toEqual(['Trend', 'Funnel', 'Retention', 'Paths', 'Stickiness', 'Lifecycle'])
    })

    it('renders Products as the last category, merging caller-supplied product commands', () => {
        // Grouping is first-occurrence order, so a command inserted in the wrong array
        // silently pulls the Products group up the menu.
        const { commands } = build([{ key: 'product-flag', label: 'Feature flag', category: 'Products', run: noop }])
        const categories = Object.keys(groupInsertCommandsByCategory(commands))

        expect(categories[categories.length - 1]).toEqual('Products')
        expect(groupInsertCommandsByCategory(commands)['Products'].map((command) => command.label)).toEqual([
            'Session recordings',
            'Feature flag',
        ])
    })
})
