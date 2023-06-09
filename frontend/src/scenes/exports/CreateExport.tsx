import { useCallback, useRef } from 'react'
import { SceneExport } from '../sceneTypes'
import { PureField } from '../../lib/forms/Field'
import { LemonInput } from '../../lib/lemon-ui/LemonInput/LemonInput'
import { useValues } from 'kea'
import { router } from 'kea-router'
import { LemonButton } from '../../lib/lemon-ui/LemonButton'
import { useCreateExport, useCurrentTeamId } from './api'
import { LemonSelect } from '../../lib/lemon-ui/LemonSelect'
import { urls } from '../urls'

export const scene: SceneExport = {
    component: CreateExport,
}

export function CreateExport(): JSX.Element {
    // Get the export type from the URL. We use the useValues hook to get the
    // current URL, and then use the useParams hook to get the export type from
    // the URL.
    const { currentTeamId } = useCurrentTeamId()
    const { currentLocation } = useValues(router)
    const exportType = currentLocation.pathname.split('/').pop()

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
            <h1>Create Export: {exportType}</h1>
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
                <LemonInput placeholder="my-secret-access-key" ref={secretAccessKeyRef} />
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
