import { LemonDialog } from 'lib/lemon-ui/LemonDialog'

export function confirmPendingSelfManagedSync(
    count: number,
    onConfirm: () => void,
    scope: 'single' | 'bulk' = 'single'
): void {
    LemonDialog.open({
        title:
            scope === 'single'
                ? 'Import this table into PostHog?'
                : `Import ${count} ${count === 1 ? 'table' : 'tables'} into PostHog?`,
        description:
            count === 1
                ? 'Right now this table reads the files in your bucket directly, at no charge. When you turn on syncing, PostHog imports the data into PostHog and keeps it up to date on the schedule you choose. Synced rows count toward your data warehouse usage and can incur charges.'
                : 'Right now these tables read the files in your bucket directly, at no charge. When you turn on syncing, PostHog imports the data into PostHog and keeps it up to date on the schedule you choose. Synced rows count toward your data warehouse usage and can incur charges.',
        primaryButton: { children: 'Turn on syncing', type: 'primary', onClick: onConfirm },
        secondaryButton: { children: 'Cancel', type: 'tertiary' },
    })
}
