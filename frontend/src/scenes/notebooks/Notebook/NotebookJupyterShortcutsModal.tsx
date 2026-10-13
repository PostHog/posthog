import { KeyboardShortcut } from 'lib/components/KeyboardShortcut/KeyboardShortcut'
import { useNotebookJupyterCommands, useNotebookJupyterStoreValue } from 'lib/components/MarkdownNotebook/jupyterMode'
import { LemonModal } from 'lib/lemon-ui/LemonModal'

import { HotKeyOrModifier } from '~/types'

type Shortcut = {
    /** Each entry is one key press. The entries are alternatives, unless `sequence` is set. */
    keys: HotKeyOrModifier[][]
    description: string
    sequence?: boolean
}

const COMMAND_MODE_SHORTCUTS: Shortcut[] = [
    { keys: [['enter']], description: 'Edit the selected cell' },
    { keys: [['shift', 'enter']], description: 'Run the cell and select the next one' },
    { keys: [['command', 'enter']], description: 'Run the cell' },
    { keys: [['option', 'enter']], description: 'Run the cell and insert a new one below' },
    { keys: [['a']], description: 'Insert a cell above' },
    { keys: [['b']], description: 'Insert a cell below' },
    { keys: [['d'], ['d']], sequence: true, description: 'Delete the cell' },
    { keys: [['z']], description: 'Undo the last cell deletion' },
    { keys: [['c']], description: 'Copy the cell' },
    { keys: [['x']], description: 'Cut the cell' },
    { keys: [['v']], description: 'Paste the cell below' },
    { keys: [['shift', 'v']], description: 'Paste the cell above' },
    { keys: [['shift', 'm']], description: 'Merge the selected cells, or the cell and the one below' },
    { keys: [['m']], description: 'Change the cell to markdown' },
    { keys: [['y']], description: 'Change the cell to code' },
    { keys: [['k'], ['arrowup']], description: 'Select the cell above' },
    { keys: [['j'], ['arrowdown']], description: 'Select the cell below' },
    {
        keys: [
            ['shift', 'arrowup'],
            ['shift', 'arrowdown'],
        ],
        description: 'Select several cells',
    },
    { keys: [['command', 'shift', 'arrowup']], description: 'Move the cell up' },
    { keys: [['command', 'shift', 'arrowdown']], description: 'Move the cell down' },
    { keys: [['i'], ['i']], sequence: true, description: 'Interrupt the running cell' },
    { keys: [['0'], ['0']], sequence: true, description: 'Restart the kernel' },
    { keys: [['o']], description: 'Show or hide the output' },
    { keys: [['l']], description: 'Show or hide line numbers' },
    { keys: [['h']], description: 'Show keyboard shortcuts' },
]

const EDIT_MODE_SHORTCUTS: Shortcut[] = [
    { keys: [['escape']], description: 'Leave the editor and select the cell' },
    { keys: [['shift', 'enter']], description: 'Run the cell and select the next one' },
    { keys: [['command', 'enter']], description: 'Run the cell' },
    { keys: [['option', 'enter']], description: 'Run the cell and insert a new one below' },
    { keys: [['command', 'shift', 'minus']], description: 'Split the cell at the cursor' },
    { keys: [['tab']], description: 'Complete the name at the cursor' },
    { keys: [['shift', 'tab']], description: 'Show the docs for the name at the cursor' },
    { keys: [['command', 'forwardslash']], description: 'Comment or uncomment the selected lines' },
    { keys: [['command', 's']], description: 'Save the notebook' },
]

function ShortcutTable({ title, shortcuts }: { title: string; shortcuts: Shortcut[] }): JSX.Element {
    return (
        <div className="flex-1 min-w-60">
            <h4 className="mb-2">{title}</h4>
            <table className="w-full text-sm">
                <tbody>
                    {shortcuts.map((shortcut) => (
                        <tr key={shortcut.description}>
                            <td className="py-1 pr-4 whitespace-nowrap">
                                {shortcut.keys.map((keys, index) => (
                                    <span key={index}>
                                        {index > 0 ? (
                                            <span className="mx-1 text-secondary">
                                                {shortcut.sequence ? ',' : 'or'}
                                            </span>
                                        ) : null}
                                        <KeyboardShortcut
                                            preserveOrder
                                            {...Object.fromEntries(keys.map((key) => [key, true]))}
                                        />
                                    </span>
                                ))}
                            </td>
                            <td className="py-1 text-secondary">{shortcut.description}</td>
                        </tr>
                    ))}
                </tbody>
            </table>
        </div>
    )
}

export function NotebookJupyterShortcutsModal(): JSX.Element | null {
    const jupyter = useNotebookJupyterCommands()
    const isOpen = useNotebookJupyterStoreValue((state) => state.shortcutsOpen)

    if (!jupyter) {
        return null
    }

    return (
        <LemonModal
            isOpen={isOpen}
            onClose={() => jupyter.store.setShortcutsOpen(false)}
            title="Keyboard shortcuts"
            description="A selected cell is in command mode. Press Enter to edit it, and Escape to go back."
            width={880}
        >
            <div className="flex flex-wrap gap-8">
                <ShortcutTable title="Command mode" shortcuts={COMMAND_MODE_SHORTCUTS} />
                <ShortcutTable title="Edit mode" shortcuts={EDIT_MODE_SHORTCUTS} />
            </div>
        </LemonModal>
    )
}
