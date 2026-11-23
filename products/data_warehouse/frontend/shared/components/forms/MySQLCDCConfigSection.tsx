import { Group } from 'kea-forms'

import { LemonDivider, LemonSwitch, LemonTag } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

export function MySQLCDCConfigSection({ prerequisitesCheck }: { prerequisitesCheck: JSX.Element }): JSX.Element {
    return (
        <Group name="payload">
            <LemonField name="cdc_enabled" className="mt-4">
                {({ value: cdcEnabled, onChange }) => (
                    <div className="rounded border border-success/40 bg-success-highlight/20 p-4">
                        <div className="flex items-start justify-between gap-4">
                            <div>
                                <div className="flex items-center gap-2 mb-1">
                                    <h4 className="mb-0 text-base font-semibold">Change data capture (CDC)</h4>
                                    <LemonTag type="warning">Beta</LemonTag>
                                </div>
                                <p className="text-sm text-secondary mb-2">
                                    Streams inserts, updates, and <strong>deletes</strong> from the MySQL binary log.
                                    Changes are captured all the time and loaded into each table on its sync schedule,
                                    every 5 minutes by default.
                                </p>
                            </div>
                            <LemonSwitch checked={!!cdcEnabled} onChange={onChange} />
                        </div>
                        <LemonDivider className="my-3" />
                        <p className="text-xs m-0 mb-1">Your database needs:</p>
                        <ul className="list-disc ml-5 space-y-1 text-xs mb-3">
                            <li>MySQL 8.0.1 or later. MariaDB and PlanetScale aren't supported yet.</li>
                            <li>
                                <code>binlog_format=ROW</code>, <code>binlog_row_image=FULL</code> and{' '}
                                <code>binlog_row_metadata=FULL</code>. On RDS and Aurora, set them in the parameter
                                group and turn on automated backups.
                            </li>
                            <li>
                                At least 24 hours of binary log retention, 7 days recommended. On RDS and Aurora, run{' '}
                                <code>CALL mysql.rds_set_configuration('binlog retention hours', 168);</code>
                            </li>
                            <li>
                                A database user with <code>REPLICATION SLAVE</code>, <code>REPLICATION CLIENT</code> and{' '}
                                <code>PROCESS</code>, plus <code>SELECT</code> on the synced tables.
                            </li>
                            <li>A primary key on every table you sync with CDC.</li>
                        </ul>
                        {prerequisitesCheck}
                    </div>
                )}
            </LemonField>
        </Group>
    )
}
