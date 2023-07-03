import { dayjs } from 'lib/dayjs'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonCalendarSelect } from 'lib/lemon-ui/LemonCalendar/LemonCalendarSelect'
import { LemonInput } from '../../lib/lemon-ui/LemonInput/LemonInput'
import { LemonSelect } from '../../lib/lemon-ui/LemonSelect'
import { Popover } from 'lib/lemon-ui/Popover/Popover'
import { PureField } from '../../lib/forms/Field'
import { router } from 'kea-router'
import { SceneExport } from '../sceneTypes'
import { useCallback, useRef, useState } from 'react'
import { useCreateExport, useCurrentTeamId } from './api'
import { urls } from '../urls'

// TODO: rewrite this to not use explicit refs for the form fields. Possibly use
// kea-forms instead.

// TODO: this file could end up getting pretty large. We should split when it
// before too much.

// TODO: if we want to enable e.g. adding a new export destination type without
// having to change this codebase we might want to consider defining either some
// configuration description of the export types, or having the config component
// be injected somehow from elsewhere. We're early days so I don't think we need
// to worry about this right now.

export const scene: SceneExport = {
    component: CreateExport,
}

export function CreateExport(): JSX.Element {
    // At the top level we offer a select to choose the export type, and then
    // render the appropriate component for that export type.
    const [exportType, setExportType] = useState<'S3' | 'Snowflake'>('S3')
    const [exportStartAt, setExportStartAt] = useState<dayjs.Dayjs | null>(null)
    const [exportEndAt, setExportEndAt] = useState<dayjs.Dayjs | null>(null)
    const [startAtSelectVisible, setStartAtSelectVisible] = useState<boolean>(false)
    const [endAtSelectVisible, setEndAtSelectVisible] = useState<boolean>(false)

    return (
        // a form for inputting the config for an export, using aria labels to
        // make it accessible.
        <form aria-label="Create Export">
            <h1>Create Export</h1>
            <PureField htmlFor="type" label="Type">
                <LemonSelect
                    id="type"
                    options={[
                        { value: 'S3', label: 'S3' },
                        { value: 'Snowflake', label: 'Snowflake' },
                    ]}
                    value={exportType}
                    onChange={(value) => setExportType(value as any)}
                />
            </PureField>
            <PureField htmlFor="type" label="Start date" showOptional={true}>
                <Popover
                    actionable
                    onClickOutside={function onClickOutside() {
                        setStartAtSelectVisible(false)
                    }}
                    visible={startAtSelectVisible}
                    overlay={
                        <LemonCalendarSelect
                            value={exportStartAt}
                            onChange={(value) => {
                                setExportStartAt(value)
                                setStartAtSelectVisible(false)
                            }}
                            onClose={function noRefCheck() {
                                setStartAtSelectVisible(false)
                            }}
                        />
                    }
                >
                    <LemonButton
                        onClick={function onClick() {
                            setStartAtSelectVisible(!startAtSelectVisible)
                        }}
                        type="secondary"
                    >
                        {exportStartAt ? exportStartAt.format('MMMM D, YYYY') : 'Select start date (optional)'}
                    </LemonButton>
                </Popover>
            </PureField>
            <PureField htmlFor="type" label="End date" showOptional={true}>
                <Popover
                    actionable
                    onClickOutside={function onClickOutside() {
                        setEndAtSelectVisible(false)
                    }}
                    visible={endAtSelectVisible}
                    overlay={
                        <LemonCalendarSelect
                            value={exportEndAt}
                            onChange={(value) => {
                                setExportEndAt(value)
                                setEndAtSelectVisible(false)
                            }}
                            onClose={function noRefCheck() {
                                setEndAtSelectVisible(false)
                            }}
                        />
                    }
                >
                    <LemonButton
                        onClick={function onClick() {
                            setEndAtSelectVisible(!endAtSelectVisible)
                        }}
                        type="secondary"
                    >
                        {exportEndAt ? exportEndAt.format('MMMM D, YYYY') : 'Select end date (optional)'}
                    </LemonButton>
                </Popover>
            </PureField>
            {exportType === 'S3' && <CreateS3Export startAt={exportStartAt} endAt={exportEndAt} />}
            {exportType === 'Snowflake' && <CreateSnowflakeExport startAt={exportStartAt} endAt={exportEndAt} />}
        </form>
    )
}

export interface ExportCommonProps {
    startAt: dayjs.Dayjs | null
    endAt: dayjs.Dayjs | null
}

export function CreateS3Export({ startAt, endAt }: ExportCommonProps): JSX.Element {
    const { currentTeamId } = useCurrentTeamId()

    // We use references to elements rather than maintaining state for each
    // field. This is a bit more verbose but it means we avoids risks of
    // re-rendering the component.
    // TODO: use kea-forms instead.
    const nameRef = useRef<HTMLInputElement>(null)
    const bucketRef = useRef<HTMLInputElement>(null)
    const prefixRef = useRef<HTMLInputElement>(null)
    const regionRef = useRef<string | null>(null)
    const accessKeyIdRef = useRef<HTMLInputElement>(null)
    const secretAccessKeyRef = useRef<HTMLInputElement>(null)
    const intervalRef = useRef<'hour' | 'day' | null>(null)

    const { createExport, loading, error } = useCreateExport()

    const handleCreateExport = useCallback(() => {
        if (
            !nameRef.current ||
            !bucketRef.current ||
            !prefixRef.current ||
            !regionRef.current ||
            !accessKeyIdRef.current ||
            !secretAccessKeyRef.current ||
            !intervalRef.current
        ) {
            console.warn('Missing ref')
        }

        // Get the values from the form fields.
        const name = nameRef.current?.value ?? ''
        const bucket = bucketRef.current?.value ?? ''
        const prefix = prefixRef.current?.value ?? ''
        const region = regionRef.current ?? ''
        const accessKeyId = accessKeyIdRef.current?.value ?? ''
        const secretAccessKey = secretAccessKeyRef.current?.value ?? ''
        const interval = intervalRef.current ?? ''

        const exportData = {
            name,
            destination: {
                type: 'S3',
                config: {
                    bucket_name: bucket,
                    region: region,
                    prefix: prefix,
                    batch_window_size: 3600,
                    aws_access_key_id: accessKeyId,
                    aws_secret_access_key: secretAccessKey,
                },
            },
            interval: interval || 'hour',
            start_at: startAt ? startAt.format('YYYY-MM-DDTHH:mm:ss.SSSZ') : null,
            end_at: endAt ? endAt.format('YYYY-MM-DDTHH:mm:ss.SSSZ') : null,
        } as const

        // Create the export.
        createExport(currentTeamId, exportData).then(() => {
            // Navigate back to the exports list.
            router.actions.push(urls.exports())
        })
    }, [startAt, endAt])

    return (
        <div>
            <PureField label="Name" htmlFor="name">
                <LemonInput id="name" placeholder="My export" ref={nameRef} />
            </PureField>

            <PureField label="Bucket" htmlFor="bucket">
                <LemonInput id="bucket" placeholder="my-bucket" ref={bucketRef} />
            </PureField>

            <PureField label="Region" htmlFor="region">
                <LemonSelect
                    id="region"
                    onSelect={(value) => {
                        regionRef.current = value
                    }}
                    options={[
                        { value: 'us-east-1', label: 'US East (N. Virginia)' },
                        { value: 'us-east-2', label: 'US East (Ohio)' },
                        { value: 'us-west-1', label: 'US West (N. California)' },
                        { value: 'us-west-2', label: 'US West (Oregon)' },
                        { value: 'af-south-1', label: 'Africa (Cape Town)' },
                        { value: 'ap-east-1', label: 'Asia Pacific (Hong Kong)' },
                        { value: 'ap-south-1', label: 'Asia Pacific (Mumbai)' },
                        { value: 'ap-northeast-3', label: 'Asia Pacific (Osaka-Local)' },
                        { value: 'ap-northeast-2', label: 'Asia Pacific (Seoul)' },
                        { value: 'ap-southeast-1', label: 'Asia Pacific (Singapore)' },
                        { value: 'ap-southeast-2', label: 'Asia Pacific (Sydney)' },
                        { value: 'ap-northeast-1', label: 'Asia Pacific (Tokyo)' },
                        { value: 'ca-central-1', label: 'Canada (Central)' },
                        { value: 'cn-north-1', label: 'China (Beijing)' },
                        { value: 'cn-northwest-1', label: 'China (Ningxia)' },
                        { value: 'eu-central-1', label: 'Europe (Frankfurt)' },
                        { value: 'eu-west-1', label: 'Europe (Ireland)' },
                        { value: 'eu-west-2', label: 'Europe (London)' },
                        { value: 'eu-south-1', label: 'Europe (Milan)' },
                        { value: 'eu-west-3', label: 'Europe (Paris)' },
                        { value: 'eu-north-1', label: 'Europe (Stockholm)' },
                        { value: 'me-south-1', label: 'Middle East (Bahrain)' },
                        { value: 'sa-east-1', label: 'South America (São Paulo)' },
                    ]}
                />
            </PureField>

            <PureField htmlFor="prefix" label="Key prefix">
                <LemonInput id="prefix" placeholder="posthog-events/" ref={prefixRef} />
            </PureField>

            <PureField htmlFor="aws-access-key-id" label="AWS Access Key ID">
                <LemonInput id="aws-access-key-id" placeholder="my-access-key-id" ref={accessKeyIdRef} />
            </PureField>

            <PureField htmlFor="aws-secret-access-key" label="AWS Secret Access Key">
                <LemonInput
                    id="aws-secret-access-key"
                    placeholder="my-secret-access-key"
                    type="password"
                    ref={secretAccessKeyRef}
                />
            </PureField>

            <PureField htmlFor="frequency" label="Frequency">
                <LemonSelect
                    id="frequency"
                    onSelect={(value: 'hour' | 'day') => {
                        intervalRef.current = value
                    }}
                    options={[
                        { value: 'hour', label: 'Hourly' },
                        { value: 'day', label: 'Daily' },
                    ]}
                />
            </PureField>

            <LemonButton onClick={handleCreateExport}>Create Export</LemonButton>

            {loading && <div>Saving...</div>}
            {error && <div>Error: {error?.toString()}</div>}
        </div>
    )
}

export function CreateSnowflakeExport({ startAt, endAt }: ExportCommonProps): JSX.Element {
    const { currentTeamId } = useCurrentTeamId()

    // Matches up with the backend config schema:
    //
    //   user: str
    //   password: str
    //   account: str
    //   database: str
    //   warehouse: str
    //   schema: str
    //   table_name: str = "events"
    //

    const nameRef = useRef<HTMLInputElement>(null)
    const userRef = useRef<HTMLInputElement>(null)
    const passwordRef = useRef<HTMLInputElement>(null)
    const accountRef = useRef<HTMLInputElement>(null)
    const databaseRef = useRef<HTMLInputElement>(null)
    const warehouseRef = useRef<HTMLInputElement>(null)
    const schemaRef = useRef<HTMLInputElement>(null)
    const tableNameRef = useRef<HTMLInputElement>(null)
    const intervalRef = useRef<'hour' | 'day' | null>(null)

    const { createExport, loading, error } = useCreateExport()

    const handleCreateExport = useCallback(() => {
        if (
            !nameRef.current ||
            !userRef.current ||
            !passwordRef.current ||
            !accountRef.current ||
            !databaseRef.current ||
            !warehouseRef.current ||
            !schemaRef.current ||
            !tableNameRef.current
        ) {
            console.warn('Missing ref')
        }

        // Get the values from the form fields.
        const name = nameRef.current?.value ?? ''
        const user = userRef.current?.value ?? ''
        const password = passwordRef.current?.value ?? ''
        const account = accountRef.current?.value ?? ''
        const database = databaseRef.current?.value ?? ''
        const warehouse = warehouseRef.current?.value ?? ''
        const schema = schemaRef.current?.value ?? ''
        const tableName = tableNameRef.current?.value ?? ''
        const interval = intervalRef.current

        const exportData = {
            name,
            destination: {
                type: 'Snowflake',
                config: {
                    user,
                    password,
                    account,
                    database,
                    warehouse,
                    schema,
                    table_name: tableName,
                },
            },
            interval: interval || 'hour',
            start_at: startAt ? startAt.format('YYYY-MM-DDTHH:mm:ss.SSSZ') : null,
            end_at: endAt ? endAt.format('YYYY-MM-DDTHH:mm:ss.SSSZ') : null,
        } as const

        // Create the export.
        createExport(currentTeamId, exportData).then(() => {
            // Navigate back to the exports list.
            router.actions.push(urls.exports())
        })
    }, [startAt, endAt])

    return (
        <div>
            <PureField label="Name">
                <LemonInput placeholder="My export" ref={nameRef} />
            </PureField>

            <PureField label="User">
                <LemonInput placeholder="my-user" ref={userRef} />
            </PureField>

            <PureField label="Password">
                <LemonInput placeholder="my-password" type="password" ref={passwordRef} />
            </PureField>

            <PureField label="Account">
                <LemonInput placeholder="my-account" ref={accountRef} />
            </PureField>

            <PureField label="Database">
                <LemonInput placeholder="my-database" ref={databaseRef} />
            </PureField>

            <PureField label="Warehouse">
                <LemonInput placeholder="my-warehouse" ref={warehouseRef} />
            </PureField>

            <PureField label="Schema">
                <LemonInput placeholder="my-schema" ref={schemaRef} />
            </PureField>

            <PureField label="Table name">
                <LemonInput placeholder="events" ref={tableNameRef} />
            </PureField>

            <PureField label="Frequency">
                <LemonSelect
                    onSelect={(value: 'hour' | 'day') => {
                        intervalRef.current = value
                    }}
                    options={[
                        { value: 'hour', label: 'Hourly' },
                        { value: 'day', label: 'Daily' },
                    ]}
                />
            </PureField>

            <LemonButton onClick={handleCreateExport}>Create Export</LemonButton>

            {loading && <div>Saving...</div>}
            {error && <div>Error: {error?.toString()}</div>}
        </div>
    )
}
