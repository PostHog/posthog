import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { router } from 'kea-router'

import { LemonButton, LemonCheckbox, LemonInput, LemonSelect } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { syntheticMonitorLogic } from './syntheticMonitorLogic'

export const scene: SceneExport = {
    component: SyntheticMonitor,
    logic: syntheticMonitorLogic,
    paramsToProps: ({ params: { id } }) => ({ id: id || 'new' }),
}

export function SyntheticMonitor(): JSX.Element {
    const { monitor, isMonitorFormSubmitting } = useValues(syntheticMonitorLogic)
    const { submitMonitorForm } = useActions(syntheticMonitorLogic)

    const isNew = !monitor?.id

    return (
        <div className="max-w-4xl">
            <div className="mb-6">
                <LemonButton type="secondary" onClick={() => router.actions.push(urls.syntheticMonitoring())}>
                    ← Back to monitors
                </LemonButton>
            </div>

            <h1 className="text-3xl font-bold mb-2">{isNew ? 'New monitor' : 'Edit monitor'}</h1>
            <p className="text-muted mb-6">
                Configure an HTTP endpoint monitor to track uptime, latency, and get alerts when issues occur
            </p>

            <Form logic={syntheticMonitorLogic} formKey="monitorForm" enableFormOnSubmit className="space-y-6">
                <div className="bg-bg-light border rounded p-6 space-y-4">
                    <h2 className="text-xl font-semibold mb-4">1. Configure monitor</h2>

                    <div className="flex gap-4">
                        <LemonField name="enabled" label="">
                            {({ value, onChange }) => (
                                <LemonCheckbox checked={value} onChange={onChange} label="Monitor enabled" />
                            )}
                        </LemonField>
                    </div>

                    <LemonField name="name" label="Name (required)">
                        <LemonInput placeholder="My API endpoint" />
                    </LemonField>

                    <LemonField name="url" label="URL (required)">
                        <LemonInput placeholder="https://api.example.com/health" />
                    </LemonField>

                    <div className="grid grid-cols-2 gap-4">
                        <LemonField name="method" label="HTTP Method">
                            <LemonSelect
                                options={[
                                    { label: 'GET', value: 'GET' },
                                    { label: 'POST', value: 'POST' },
                                    { label: 'PUT', value: 'PUT' },
                                    { label: 'PATCH', value: 'PATCH' },
                                    { label: 'DELETE', value: 'DELETE' },
                                    { label: 'HEAD', value: 'HEAD' },
                                ]}
                            />
                        </LemonField>

                        <LemonField name="expected_status_code" label="Expected status code">
                            <LemonInput type="number" placeholder="200" />
                        </LemonField>
                    </div>

                    <div className="grid grid-cols-2 gap-4">
                        <LemonField name="frequency_minutes" label="Check frequency">
                            <LemonSelect
                                options={[
                                    { label: 'Every 1 minute', value: 1 },
                                    { label: 'Every 5 minutes', value: 5 },
                                    { label: 'Every 15 minutes', value: 15 },
                                    { label: 'Every 30 minutes', value: 30 },
                                    { label: 'Every 60 minutes', value: 60 },
                                ]}
                            />
                        </LemonField>

                        <LemonField name="timeout_seconds" label="Timeout (seconds)">
                            <LemonInput type="number" placeholder="30" />
                        </LemonField>
                    </div>

                    <LemonField name="body" label="Request body (optional)">
                        <LemonInput placeholder='{"key": "value"}' />
                    </LemonField>
                </div>

                <div className="bg-bg-light border rounded p-6 space-y-4">
                    <h2 className="text-xl font-semibold mb-4">2. Select locations</h2>

                    <LemonField name="regions" label="Regions" help="Select AWS regions to run checks from">
                        <LemonSelect
                            mode="multiple"
                            placeholder="Select regions"
                            options={[
                                { label: 'US East (N. Virginia)', value: 'us-east-1' },
                                { label: 'US West (Oregon)', value: 'us-west-2' },
                                { label: 'EU West (Ireland)', value: 'eu-west-1' },
                                { label: 'EU Central (Frankfurt)', value: 'eu-central-1' },
                                { label: 'Asia Pacific (Singapore)', value: 'ap-southeast-1' },
                                { label: 'Asia Pacific (Tokyo)', value: 'ap-northeast-1' },
                            ]}
                        />
                    </LemonField>
                </div>

                <div className="bg-bg-light border rounded p-6 space-y-4">
                    <h2 className="text-xl font-semibold mb-4">3. Alerts (optional)</h2>

                    <LemonField name="alert_enabled" label="">
                        {({ value, onChange }) => (
                            <LemonCheckbox checked={value} onChange={onChange} label="Enable alerts" />
                        )}
                    </LemonField>

                    <LemonField name="alert_threshold_failures" label="Alert after consecutive failures">
                        <LemonInput type="number" placeholder="3" />
                    </LemonField>
                </div>

                <div className="flex gap-2">
                    <LemonButton
                        type="secondary"
                        onClick={() => router.actions.push(urls.syntheticMonitoring())}
                        disabled={isMonitorFormSubmitting}
                    >
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        htmlType="submit"
                        loading={isMonitorFormSubmitting}
                        onClick={submitMonitorForm}
                    >
                        Save monitor
                    </LemonButton>
                </div>
            </Form>
        </div>
    )
}
