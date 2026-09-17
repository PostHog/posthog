import { LemonDialog } from 'lib/lemon-ui/LemonDialog'

export function openAccountDetailWorkInProgress(title: string): void {
    LemonDialog.open({
        title,
        content: 'This feature is a work in progress.',
    })
}
