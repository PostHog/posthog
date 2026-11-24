import { LemonDialog, LemonSelect } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

import { DataWarehouseSyncInterval, ExternalDataSourceSchema } from '~/types'

import { SyncFrequencyLabelMap, allowedSyncFrequencies } from 'products/data_warehouse/frontend/utils'

// Migrated tables come with the model's 6 hour default, which nobody picked. Daily is the default
// we offer instead, because each full refresh bills every row again.
export const DEFAULT_PENDING_SELF_MANAGED_SYNC_FREQUENCY: DataWarehouseSyncInterval = '24hour'

const BUCKET_READ_NOTE = 'Right now this table reads the files in your bucket directly, at no charge.'
const BILLING_NOTE = 'Synced rows count toward your data warehouse usage and can incur charges.'

export function singleTableFullRefreshNote(syncType: ExternalDataSourceSchema['sync_type']): string {
    if (syncType !== 'full_refresh') {
        return ''
    }
    return ' This table uses full refresh, so each sync imports every row again and bills each of those rows. If the table supports incremental sync, choose it as the sync method so that each sync imports only new and changed rows.'
}

function SyncFrequencyField({ dataAttr }: { dataAttr: string }): JSX.Element {
    return (
        <LemonField name="syncFrequency" label="Sync frequency">
            <LemonSelect
                options={allowedSyncFrequencies().map((frequency) => ({
                    value: frequency,
                    label: SyncFrequencyLabelMap[frequency],
                }))}
                data-attr={dataAttr}
            />
        </LemonField>
    )
}

// Turns on scheduled syncing for one migrated table, so it asks for the frequency as well.
export function confirmPendingSelfManagedSync(
    syncType: ExternalDataSourceSchema['sync_type'],
    onConfirm: (syncFrequency: DataWarehouseSyncInterval) => void
): void {
    LemonDialog.openForm({
        title: 'Import this table into PostHog?',
        description: `${BUCKET_READ_NOTE} When you turn on syncing, PostHog imports the data into PostHog and keeps it up to date on the schedule you choose below. ${BILLING_NOTE}${singleTableFullRefreshNote(syncType)}`,
        initialValues: { syncFrequency: DEFAULT_PENDING_SELF_MANAGED_SYNC_FREQUENCY },
        content: <SyncFrequencyField dataAttr="pending-self-managed-sync-frequency" />,
        primaryButtonProps: { children: 'Turn on syncing' },
        onSubmit: ({ syncFrequency }) => onConfirm(syncFrequency),
    })
}

// A manual sync runs once and leaves the schedule off, so there is no frequency to ask for.
export function confirmPendingSelfManagedReload(
    syncType: ExternalDataSourceSchema['sync_type'],
    onConfirm: () => void
): void {
    LemonDialog.open({
        title: 'Import this table into PostHog?',
        description: `${BUCKET_READ_NOTE} When you sync it, PostHog imports the data into PostHog. After that, the table reads the copy in PostHog instead of your bucket. The copy updates only when you sync it again or turn on syncing. ${BILLING_NOTE}${singleTableFullRefreshNote(syncType)}`,
        primaryButton: { children: 'Sync now', type: 'primary', onClick: onConfirm },
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
        description: `Right now ${count === 1 ? 'this table reads' : 'these tables read'} the files in your bucket directly, at no charge. When you turn on syncing, PostHog imports the data into PostHog and keeps it up to date on the schedule you choose below. ${BILLING_NOTE}${fullRefreshNote(pendingSchemas)} You can change the sync method and frequency of each table later.`,
        initialValues: { syncFrequency: DEFAULT_PENDING_SELF_MANAGED_SYNC_FREQUENCY },
        content: <SyncFrequencyField dataAttr="pending-self-managed-bulk-sync-frequency" />,
        primaryButtonProps: { children: 'Turn on syncing' },
        onSubmit: ({ syncFrequency }) => onConfirm(syncFrequency),
    })
}
