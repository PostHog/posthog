import React, { useState } from 'react'
import { Button, Card, Input, Select, Tooltip } from 'antd'
import { useActions, useValues } from 'kea'
import { systemStatusLogic } from 'scenes/instance/SystemStatus/systemStatusLogic'
import Paragraph from 'antd/lib/typography/Paragraph'

export function BackupTab(): JSX.Element {
    const { systemStatus } = useValues(systemStatusLogic)
    const { createBackup, restoreFromBackup } = useActions(systemStatusLogic)
    const [ restoreCandidate, setRestoreCandidate] = useState('')
    const [ backupSuffix, setBackupSuffix] = useState('')
    const defaultSuffix = "ui"

    return (
        <>
            <Card>
                {console.log("In backup tab")}
                {systemStatus?.backup.is_enabled ? (
                    <>
                        <Tooltip title={`Only alphanumeric-_ are accepted. Default suffix is \"${defaultSuffix}\"`}
                        >
                            <Input 
                                style={{ width: 400 }}
                                addonBefore="YYYY-MM-DD-HH-mm-" 
                                placeholder="Optional custom suffix" 
                                onChange={(value) => setBackupSuffix(value.target.value.replace(/[^\w\-]/g, ''))}
                            />
                        </Tooltip>
                        &nbsp;&nbsp;
                        <Button
                            type="primary"
                            onClick={() => createBackup(`${new Date().toISOString().replace(/[:T]/g, '-').substr(0,17)}${backupSuffix?backupSuffix:defaultSuffix}`)}
                        >
                            Create Backup
                        </Button>
                        <br/> 
                        <h2 style={{ color: 'var(--danger)' }}>
                            Danger Zone
                        </h2>
                        <Paragraph type="danger">
                            This is owerwrites all data in Clickhouse. Please be certain.
                            <br/>
                        </Paragraph>
                        <Select 
                            showSearch
                            style={{ width: 400 }}
                            placeholder="Search to Select"
                            filterOption={(input, option) =>
                                  option.children.toLowerCase().indexOf(input.toLowerCase()) >= 0
                            }
                            onChange={(value) => setRestoreCandidate(value)}
                        >
                            {systemStatus?.backup.existing_bk_names.map((name) => (
                                <Select.Option key={name} value={name}>{name}</Select.Option>
                            ))}
                        </Select>
                        &nbsp;&nbsp;
                        <Button danger
                            // we probably want to restrict it to some group of users explicitly here too similar to https://github.com/PostHog/posthog/blob/2b4290959108dd6401449e9a7c1251e2dbcb980e/frontend/src/scenes/organization/Settings/index.tsx#L61 
                            // Probably want it to throw up a confirmation dialog box
                            onClick={() => restoreFromBackup(restoreCandidate)}
                        >
                            Restore From Backup
                        </Button>

                    </>
                ) : (
                  <b> Backups are currently not enabled, read how to enable backups TODO link. </b>
                )}

                {/* 1. if not existing then link to a help page, else
                  2. Show a button for a manual backup now (with an option to name it something)
                  3. dropdown to restore from a backup (admin only action, i.e. we shouldn't have that right for the posthog cloud maybe?)
                  4. settings for regular backups (mainly frequency)  <- that should maybe also be in the config file ???
                  */}
            </Card>
        </>
    )
}
