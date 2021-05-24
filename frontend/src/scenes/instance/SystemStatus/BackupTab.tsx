import React, { useState } from 'react'
import { Button, Card, Input, Select, Tooltip } from 'antd'
import { useActions, useValues } from 'kea'
import { systemStatusLogic } from 'scenes/instance/SystemStatus/systemStatusLogic'

export function BackupTab(): JSX.Element {
    const { systemStatus } = useValues(systemStatusLogic)
    const { createBackup, restoreFromBackup } = useActions(systemStatusLogic)
    const [restoreCandidate, setRestoreCandidate] = useState('')
    const [backupSuffix, setBackupSuffix] = useState('')
    const defaultSuffix = 'ui'

    return (
        <Card>
            {systemStatus?.backup.is_enabled ? (
                <>
                    <Tooltip title={`Only alphanumeric-_ are accepted. Default suffix is \"${defaultSuffix}\"`}>
                        <Input
                            style={{ width: 400 }}
                            addonBefore="YYYY-MM-DD-HH-mm-"
                            placeholder="Optional custom suffix"
                            onChange={(value) => setBackupSuffix(value.target.value.replace(/[^\w\-]/g, ''))}
                        />
                    </Tooltip>
                    &nbsp;&nbsp;
                    <Button
                        // TODO: provide some info about where the errors went
                        type="primary"
                        onClick={() =>
                            createBackup(
                                `${new Date().toISOString().replace(/[:T]/g, '-').substr(0, 17)}${
                                    backupSuffix ? backupSuffix : defaultSuffix
                                }`
                            )
                        }
                    >
                        Create Backup
                    </Button>
                    <br />
                    <br />
                    <Select
                        showSearch
                        style={{ width: 360 }}
                        placeholder="Search to Select"
                        filterOption={(input, option) =>
                            option.children.toLowerCase().indexOf(input.toLowerCase()) >= 0
                        }
                        onChange={(value) => setRestoreCandidate(value)}
                    >
                        {systemStatus?.backup.existing_backups.map((name) => (
                            <Select.Option key={name} value={name}>
                                {name}
                            </Select.Option>
                        ))}
                    </Select>
                    &nbsp;&nbsp;
                    <Button
                        type="primary"
                        // TODO: what happens if some tables exist?
                        // TODO: restoring specific tables, maybe?
                        // TODO: provide some info about where the errors went
                        onClick={() => restoreFromBackup(restoreCandidate)}
                    >
                        Restore From Backup
                    </Button>
                </>
            ) : (
                <b> Backups are currently not enabled, read how to enable backups TODO link. </b>
            )}
        </Card>
    )
}
