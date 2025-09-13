import { Extension } from '@tiptap/react'

type CommandEnterExtensionOptions = {
    onPressCmdEnter: () => void
}

export const CommandEnterExtension = Extension.create<CommandEnterExtensionOptions>({
    name: 'cmd-enter',

    addOptions() {
        return {
            onPressCmdEnter: () => {},
        }
    },

    addKeyboardShortcuts() {
        return {
            'Mod-Enter': () => {
                this.options.onPressCmdEnter()
                return true
            },
        }
    },
})
