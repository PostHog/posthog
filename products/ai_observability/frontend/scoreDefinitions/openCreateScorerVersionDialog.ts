import { LemonDialog } from 'lib/lemon-ui/LemonDialog'

export function openCreateScorerVersionDialog({
    currentVersion,
    createVersion,
}: {
    currentVersion: number
    createVersion: () => void
}): void {
    LemonDialog.open({
        title: 'Create a new scorer version?',
        content: `Version ${currentVersion + 1} will keep the current configuration. Use this when your external evaluator changes.`,
        primaryButton: { children: 'Create version', onClick: createVersion },
        secondaryButton: { children: 'Cancel' },
    })
}
