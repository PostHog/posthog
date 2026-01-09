import { Dialog } from '@base-ui/react/dialog'
import { useActions, useValues } from 'kea'

// import { Autocomplete } from '@base-ui/react/autocomplete';

import { commandLogic } from './commandLogic'

// import { Results } from 'scenes/new-tab/components/Results'

export function Command(): JSX.Element {
    const { isCommandOpen } = useValues(commandLogic)
    const { closeCommand } = useActions(commandLogic)

    return (
        <Dialog.Root open={isCommandOpen} onOpenChange={(open) => !open && closeCommand()}>
            <Dialog.Portal>
                <Dialog.Backdrop className="fixed inset-0 min-h-screen min-w-screen bg-black opacity-20 transition-all duration-150 data-[ending-style]:opacity-0 data-[starting-style]:opacity-0 dark:opacity-70" />
                <Dialog.Popup className="fixed top-1/2 left-1/2 w-[640px] max-w-[calc(100vw-3rem)] -translate-x-1/2 -translate-y-1/2 rounded-lg bg-bg-light p-0 shadow-xl border border-primary transition-all duration-150 data-[ending-style]:scale-95 data-[ending-style]:opacity-0 data-[starting-style]:scale-95 data-[starting-style]:opacity-0" />
            </Dialog.Portal>
        </Dialog.Root>
    )
}
