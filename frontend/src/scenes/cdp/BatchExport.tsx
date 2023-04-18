import { SceneExport } from 'scenes/sceneTypes'
import { DEFAULT_FILE_NAME, BatchExportLogic } from './BatchExportLogic'
import { useActions, useValues } from 'kea'
import { PageHeader } from 'lib/components/PageHeader'
import { LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { BatchExportFrequencyType, BatchExportTabsType, S3BatchExportFileFormatType } from './types'
import { Form } from 'kea-forms'
import { Field } from 'lib/forms/Field'
import { LemonButton, LemonCheckbox, LemonDivider, LemonInput, LemonLabel, LemonSelect } from '@posthog/lemon-ui'
import { DatePicker } from 'antd'
import { shortTimeZone } from 'lib/utils'
import { ActivityLog } from 'lib/components/ActivityLog/ActivityLog'
import { ActivityScope } from 'lib/components/ActivityLog/humanizeActivity'
import { ExportOverviewTab } from './ExportOverview'
import { EditOutlined } from '@ant-design/icons'

export const scene: SceneExport = {
    component: BatchExport,
    logic: BatchExportLogic,
    paramsToProps: ({ params: { id } }) => ({ id: id }),
}

const frequencyOptions: { label: string; value: BatchExportFrequencyType; noun: string }[] = [
    {
        label: 'None',
        value: 'none',
        noun: 'nothing',
    },
    {
        label: 'Every 1 hour',
        value: '1',
        noun: 'the first hour',
    },
    {
        label: 'Every 6 hours',
        value: '6',
        noun: 'the first 6 hours',
    },
    {
        label: 'Every 12 hours',
        value: '12',
        noun: 'the first 12 hours',
    },
    {
        label: 'Daily',
        value: 'daily',
        noun: 'the first day',
    },
    {
        label: 'Weekly',
        value: 'weekly',
        noun: 'the first week',
    },
    {
        label: 'Monthly',
        value: 'monthly',
        noun: 'the first month',
    },
]

const fileFormatOptions: { label: string; value: S3BatchExportFileFormatType }[] = [
    {
        label: 'CSV',
        value: 'csv',
    },
]

const generateDescription = (interval: Exclude<BatchExportFrequencyType, 'none'>): string => {
    const intervals: Record<
        Exclude<BatchExportFrequencyType, 'none'>,
        {
            period: string
            frequency: string
        }
    > = {
        '1': { period: '1-hour', frequency: 'hourly' },
        '6': { period: '6-hour', frequency: 'every 6 hours' },
        '12': { period: '12-hour', frequency: 'every 12 hours' },
        daily: { period: '24-hour', frequency: 'daily' },
        weekly: { period: '1-week', frequency: 'weekly' },
        monthly: { period: '1-month', frequency: 'monthly' },
    }

    return `The job is set to export ${intervals[interval].period} data segments ${intervals[interval].frequency}. This means only the first ${intervals[interval].period} period's data is included in the first run. To conduct an additional one-time export of all existing historical data during this first execution, enable this option.`
}

export function S3Settings(): JSX.Element {
    const {
        batchExportSettings: connectionSettings,
        editingSecret,
        timezone,
        fileNamePreview,
    } = useValues(BatchExportLogic)
    const { setEditingSecret } = useActions(BatchExportLogic)

    return (
        <Form logic={BatchExportLogic} formKey={'batchExportSettings'} className="max-w-200 border rounded p-6">
            <div>
                <h2>Connection</h2>
                <Field name={'name'} label="Display Name">
                    <LemonInput />
                </Field>
            </div>
            <LemonDivider className="my-6" />
            <div className="space-y-4">
                <h2>Export Schedule</h2>
                <Field name={'frequency'} label="Frequency">
                    <LemonSelect options={frequencyOptions} />
                </Field>
                {connectionSettings?.frequency !== 'none' && (
                    <>
                        <Field
                            name={'firstExport'}
                            label={`First export at (${shortTimeZone(timezone)})`} // TODO: add timezone tooltip similar to the created at column
                            className="max-w-60"
                        >
                            <DatePicker showTime />
                        </Field>
                        <Field name={'stopAtSpecificDate'}>
                            <LemonCheckbox label="Stop exporting after a specific date" showOptional />
                        </Field>
                        {connectionSettings?.stopAtSpecificDate && (
                            <Field
                                name={'stopAt'}
                                label={`No exports after (${shortTimeZone(timezone)})`}
                                showOptional
                                className="max-w-60"
                            >
                                <DatePicker showTime />
                            </Field>
                        )}
                    </>
                )}
            </div>
            {connectionSettings.frequency !== 'none' && (
                <>
                    <LemonDivider className="my-6" />
                    <div className="space-y-4">
                        <h2>Historical data</h2>
                        <p>{generateDescription(connectionSettings.frequency)}</p>
                        <Field name={'backfillRecords'}>
                            <LemonCheckbox label="Backfill historical data at the time of the first run" showOptional />
                        </Field>
                        {connectionSettings.backfillRecords && (
                            <Field
                                name={'backfillFrom'}
                                label={'Backfill from (' + shortTimeZone(timezone) + ')'}
                                info="If blank it will backfill all data"
                                className="max-w-60"
                            >
                                <DatePicker showTime />
                            </Field>
                        )}
                    </div>
                </>
            )}
            <LemonDivider className="my-6" />
            <div className="space-y-4">
                <h2>Destination</h2>

                <div className="space-y-4">
                    <h3>Credentials</h3>
                    <Field name={'AWSAccessKeyID'} label="AWS access key ID">
                        <LemonInput />
                    </Field>
                    <Field name={'AWSSecretAccessKey'} label="AWS secret access key">
                        {!editingSecret && connectionSettings?.AWSSecretAccessKey ? (
                            <LemonButton
                                icon={<EditOutlined />}
                                onClick={() => {
                                    setEditingSecret(true)
                                }}
                            >
                                Reset secret key
                            </LemonButton>
                        ) : (
                            <LemonInput type="password" />
                        )}
                    </Field>
                </div>
                <div className="my-6" />
                <div className="space-y-4">
                    <h3>Location</h3>
                    <Field name={'AWSRegion'} label="AWS region">
                        <LemonInput />
                    </Field>
                    <Field name={'AWSBucket'} label="S3 bucket name">
                        <LemonInput />
                    </Field>
                </div>
                <div className="my-6" />
            </div>
            <LemonDivider className="my-6" />
            <div className="space-y-4">
                <h2>Data</h2>
                <Field name={'fileFormat'} label="File format">
                    <LemonSelect options={fileFormatOptions} />
                </Field>
                <div>
                    <LemonLabel>File name</LemonLabel>
                    <p>
                        You can include the partition key and components of the timestamp. For example:
                        <br />
                        <code>{DEFAULT_FILE_NAME}</code>
                    </p>
                    <Field name={'fileName'}>
                        <LemonInput />
                    </Field>
                    <p className="text-sm text-gray-500 my-4">
                        Preview: <code style={{ color: '#0BA90A' }}>{fileNamePreview}</code>
                    </p>
                    <div />
                </div>
            </div>

            <div className="flex justify-end gap-2 border-t mt-4 pt-4">
                <LemonButton htmlType="submit" type="primary">
                    Save
                </LemonButton>
            </div>
        </Form>
    )
}

export function BatchExport(): JSX.Element {
    const {
        connectionChoice: batchExportChoice,
        activeTab,
        connection: batchExportDestination,
    } = useValues(BatchExportLogic)
    const { setTab } = useActions(BatchExportLogic)
    return (
        <>
            <PageHeader title={batchExportChoice?.name || 'undefined'} />
            <LemonTabs
                tabs={[
                    {
                        key: 'sync-history',
                        label: 'Sync History',
                        content: <ExportOverviewTab />,
                    },
                    {
                        key: 'activity-log',
                        label: 'History',
                        content: <ActivityLog scope={ActivityScope.CONNECTION} id={batchExportDestination?.id} />,
                    },
                    {
                        key: 'settings',
                        label: 'Settings',
                        content: <S3Settings />,
                    },
                ]}
                activeKey={activeTab}
                onChange={function (key: BatchExportTabsType): void {
                    setTab(key)
                }}
            />
        </>
    )
}
