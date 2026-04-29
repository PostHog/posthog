import { Extension } from '@tiptap/core'

/**
 * Splitting a block with Enter creates a plain, unstyled paragraph.
 * Does not apply when pressing Enter at the start of a block.
 */
export const NotebookDefaultBlockOnEnter = Extension.create({
    name: 'notebookDefaultBlockOnEnter',

    // Run before the built-in keymap extension (priority 100) so Enter is handled here first.
    priority: 200,

    addKeyboardShortcuts() {
        return {
            Enter: () => {
                const { $from: $before } = this.editor.state.selection
                const atStart = $before.parentOffset === 0

                if (this.editor.isActive('listItem') || this.editor.isActive('taskItem')) {
                    return false
                }

                const handled = this.editor.commands.first(({ commands }) => [
                    () => commands.newlineInCode(),
                    () => commands.createParagraphNear(),
                    () => commands.liftEmptyBlock(),
                    () => commands.splitBlock(),
                ])

                // if none of the commands worked, we shouldn't try to strip marks or convert nodes
                if (handled && !atStart) {
                    const { $from } = this.editor.state.selection
                    if ($from.parent.type.name !== 'paragraph') {
                        this.editor.commands.setNode('paragraph')
                    }

                    const { $from: $pos } = this.editor.state.selection
                    this.editor
                        .chain()
                        .setTextSelection({ from: $pos.start(), to: $pos.end() })
                        .unsetAllMarks()
                        .setTextSelection($pos.pos)
                        .run()
                }

                return handled
            },
        }
    },
})
