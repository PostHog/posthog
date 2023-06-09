import { useCallback, useRef, useState } from 'react'
import { SceneExport } from '../sceneTypes'
import { PureField } from '../../lib/forms/Field'
import { LemonInput } from '../../lib/lemon-ui/LemonInput/LemonInput'
import { router } from 'kea-router'
import { LemonButton } from '../../lib/lemon-ui/LemonButton'
import { useCreateExport, useCurrentTeamId } from './api'
import { LemonSelect } from '../../lib/lemon-ui/LemonSelect'
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

    return (
        <div>
            <h1>Create Export</h1>
            <PureField label="Type">
                <LemonSelect
                    options={[
                        { value: 'S3', label: 'S3' },
                        { value: 'Snowflake', label: 'Snowflake' },
                    ]}
                    value={exportType}
                    onChange={(value) => setExportType(value as any)}
                />
            </PureField>
            {exportType === 'S3' && <CreateS3Export />}
            {exportType === 'Snowflake' && <CreateSnowflakeExport />}
        </div>
    )
}

export function CreateS3Export(): JSX.Element {
    const { currentTeamId } = useCurrentTeamId()

    const nameRef = useRef<HTMLInputElement>(null)
    const bucketRef = useRef<HTMLInputElement>(null)
    const prefixRef = useRef<HTMLInputElement>(null)
    const accessKeyIdRef = useRef<HTMLInputElement>(null)
    const secretAccessKeyRef = useRef<HTMLInputElement>(null)

    const { createExport, loading, error } = useCreateExport()

    const handleCreateExport = useCallback(() => {
        if (
            !nameRef.current ||
            !bucketRef.current ||
            !prefixRef.current ||
            !accessKeyIdRef.current ||
            !secretAccessKeyRef.current
        ) {
            console.warn('Missing ref')
        }

        // Get the values from the form fields.
        const name = nameRef.current?.value ?? ''
        const bucket = bucketRef.current?.value ?? ''
        const prefix = prefixRef.current?.value ?? ''
        const accessKeyId = accessKeyIdRef.current?.value ?? ''
        const secretAccessKey = secretAccessKeyRef.current?.value ?? ''

        const exportData = {
            name,
            destination: {
                type: 'S3',
                config: {
                    bucket_name: bucket,
                    region: 'us-east-1', // TODO: pull this from the form
                    prefix: prefix,
                    batch_window_size: 3600,
                    aws_access_key_id: accessKeyId,
                    aws_secret_access_key: secretAccessKey,
                },
            },
            interval: 'hour', // TODO: pull this from the form
        } as const

        // Create the export.
        createExport(currentTeamId, exportData).then(() => {
            // Navigate back to the exports list.
            router.actions.push(urls.exports())
        })
    }, [])

    return (
        <div>
            <PureField label="Name">
                <LemonInput placeholder="My export" ref={nameRef} />
            </PureField>

            <PureField label="Bucket">
                <LemonInput placeholder="my-bucket" ref={bucketRef} />
            </PureField>

            <PureField label="Region">
                <LemonSelect
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

            <PureField label="Key prefix">
                <LemonInput placeholder="posthog-events/" ref={prefixRef} />
            </PureField>

            <PureField label="AWS Access Key ID">
                <LemonInput placeholder="my-access-key-id" ref={accessKeyIdRef} />
            </PureField>

            <PureField label="AWS Secret Access Key">
                <LemonInput placeholder="my-secret-access-key" type="password" ref={secretAccessKeyRef} />
            </PureField>

            <PureField label="Frequency">
                <LemonSelect
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

export function CreateSnowflakeExport(): JSX.Element {
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
            interval: 'hour', // TODO: pull this from the form
        } as const

        // Create the export.
        createExport(currentTeamId, exportData).then(() => {
            // Navigate back to the exports list.
            router.actions.push(urls.exports())
        })
    }, [])

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

            <LemonButton onClick={handleCreateExport}>Create Export</LemonButton>

            {loading && <div>Saving...</div>}
            {error && <div>Error: {error?.toString()}</div>}
        </div>
    )
}
