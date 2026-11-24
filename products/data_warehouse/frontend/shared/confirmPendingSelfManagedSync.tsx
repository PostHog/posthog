import { LemonDialog, LemonSelect } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

import { DataWarehouseSyncInterval, ExternalDataSourceSchema } from '~/types'

import { SyncFrequencyLabelMap, allowedSyncFrequencies } from 'products/data_warehouse/frontend/utils'

// Migrated tables come with the model's 6 hour default, which nobody picked. Daily is the default
// we offer instead, because each full refresh bills every row again.
export const DEFAULT_PENDING_SELF_MANAGED_SYNC_FREQUENCY: DataWarehouseSyncInterval = '24hour'

export function confirmPendingSelfManagedSync(onConfirm: () => void): void {
    LemonDialog.open({
        title: 'Import this table into PostHog?',
        description:
            'Right now this table reads the files in your bucket directly, at no charge. When you turn on syncing, PostHog imports the data into PostHog and keeps it up to date on the schedule you choose. Synced rows count toward your data warehouse usage and can incur charges.',
        primaryButton: { children: 'Turn on syncing', type: 'primary', onClick: onConfirm },
        secondaryButton: { children: 'Cancel', type: 'tertiary' },
    })
}

function fullRefreshNote(pendingSchemas: ExternalDataSourceSchema[]): string {
    const fullRefreshCount = pendingSchemas.filter((schema) => schema.sync_type === 'full_refresh').length
    if (fullRefreshCount === 0) {
        return ''
    }
    let subject = `${fullRefreshCount} of these tables use`
    if (fullRefreshCount === pendingSchemas.length) {
        subject = fullRefreshCount === 1 ? 'This table uses' : 'These tables use'
    }
    return ` ${subject} full refresh, so each sync imports every row again and bills each of those rows.`
}

export function confirmPendingSelfManagedBulkSync(
    pendingSchemas: ExternalDataSourceSchema[],
    onConfirm: (syncFrequency: DataWarehouseSyncInterval) => void
): void {
    const count = pendingSchemas.length
    LemonDialog.openForm({
        title: `Import ${count} ${count === 1 ? 'table' : 'tables'} into PostHog?`,
        description: `Right now ${count === 1 ? 'this table reads' : 'these tables read'} the files in your bucket directly, at no charge. When you turn on syncing, PostHog imports the data into PostHog and keeps it up to date on the schedule you choose below. Synced rows count toward your data warehouse usage and can incur charges.${fullRefreshNote(pendingSchemas)} You can change the sync method and frequency of each table later.`,
        initialValues: { syncFrequency: DEFAULT_PENDING_SELF_MANAGED_SYNC_FREQUENCY },
        content: (
            <LemonField name="syncFrequency" label="Sync frequency">
                <LemonSelect
                    options={allowedSyncFrequencies().map((frequency) => ({
                        value: frequency,
                        label: SyncFrequencyLabelMap[frequency],
                    }))}
                    data-attr="pending-self-managed-bulk-sync-frequency"
                />
            </LemonField>
        ),
        primaryButtonProps: { children: 'Turn on syncing' },
        onSubmit: ({ syncFrequency }) => onConfirm(syncFrequency),
    })
}
