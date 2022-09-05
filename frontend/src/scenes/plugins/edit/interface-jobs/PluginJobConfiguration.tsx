import React, { useMemo } from 'react'
import { PlayCircleOutlined, CheckOutlined, CloseOutlined, SettingOutlined } from '@ant-design/icons'
import { Tooltip, Radio, InputNumber, DatePicker } from 'antd'
import { ChildFunctionProps, Form } from 'kea-forms'
import { Field } from 'lib/forms/Field'
import Modal from 'antd/lib/modal/Modal'
import MonacoEditor from '@monaco-editor/react'
import { useValues, useActions } from 'kea'
import { userLogic } from 'scenes/userLogic'
import { JobPayloadFieldOptions, JobSpec } from '~/types'
import { interfaceJobsLogic } from './interfaceJobsLogic'
import { LemonInput } from '../../../../lib/components/LemonInput/LemonInput'
import moment from 'moment'

interface PluginJobConfigurationProps {
    jobName: string
    jobSpec: JobSpec
    pluginConfigId: number
    pluginId: number
}

// keep in sync with plugin-server's export-historical-events.ts
export const HISTORICAL_EXPORT_JOB_NAME = 'Export historical events'
export const HISTORICAL_EXPORT_JOB_NAME_V2 = 'Export historical events V2'

export function PluginJobConfiguration({
    jobName,
    jobSpec,
    pluginConfigId,
    pluginId,
}: PluginJobConfigurationProps): JSX.Element {
    if ([HISTORICAL_EXPORT_JOB_NAME].includes(jobName)) {
        jobSpec.payload = {
            dateFrom: { type: 'date' },
            dateTo: { type: 'date' },
        }
    }

    const logicProps = { jobName, pluginConfigId, pluginId, jobSpecPayload: jobSpec.payload }
    const { setIsJobModalOpen, playButtonOnClick, submitJobPayload } = useActions(interfaceJobsLogic(logicProps))
    const { runJobAvailable, isJobModalOpen } = useValues(interfaceJobsLogic(logicProps))
    const { user } = useValues(userLogic)

    const jobHasEmptyPayload = Object.keys(jobSpec.payload || {}).length === 0

    const configureOrRunJobTooltip = runJobAvailable
        ? jobHasEmptyPayload
            ? `Run job`
            : `Configure and run job`
        : `You already ran this job recently.`

    const shownFields = useMemo(() => {
        return Object.entries(jobSpec.payload || {})
            .filter(([, options]) => !options.staff_only || user?.is_staff || user?.is_impersonated)
            .sort((a, b) => a[0].localeCompare(b[0]))
    }, [jobSpec, user])

    return (
        <>
            <span className="ml-1" onClick={() => playButtonOnClick(jobHasEmptyPayload)}>
                <Tooltip title={configureOrRunJobTooltip}>
                    {jobHasEmptyPayload ? (
                        <PlayCircleOutlined
                            className={runJobAvailable ? 'plugin-run-job-button' : 'plugin-run-job-button-disabled'}
                        />
                    ) : (
                        <SettingOutlined
                            className={runJobAvailable ? 'plugin-run-job-button' : 'plugin-run-job-button-disabled'}
                        />
                    )}
                </Tooltip>
            </span>

            <Modal
                visible={isJobModalOpen}
                onCancel={() => setIsJobModalOpen(false)}
                onOk={() => submitJobPayload()}
                okText={'Run job now'}
                title={`Configuring job '${jobName}'`}
            >
                {shownFields.length > 0 ? (
                    <Form logic={interfaceJobsLogic} props={logicProps} formKey="jobPayload">
                        {shownFields.map(([key, options]) => (
                            <Field name={key} label={options.title || key} key={key} className="mb-4">
                                {(props) => <FieldInput options={options} {...props} />}
                            </Field>
                        ))}
                    </Form>
                ) : null}
            </Modal>
        </>
    )
}

function FieldInput({
    options,
    value,
    onChange,
}: { options: JobPayloadFieldOptions } & ChildFunctionProps): JSX.Element {
    switch (options.type) {
        case 'string':
            return <LemonInput value={value || ''} onChange={onChange} />
        case 'number':
            return <InputNumber value={value} onChange={onChange} />
        case 'json':
            return (
                <MonacoEditor
                    theme="vs-dark"
                    options={{ codeLens: false, lineNumbers: 'off' }}
                    className="plugin-job-json-editor"
                    language="json"
                    height={200}
                    value={value}
                    onChange={onChange}
                />
            )
        case 'boolean':
            return (
                <Radio.Group
                    id="propertyValue"
                    buttonStyle="solid"
                    value={value}
                    onChange={(e) => onChange(e.target.value)}
                >
                    <Radio.Button value={true} defaultChecked>
                        <CheckOutlined /> True
                    </Radio.Button>
                    <Radio.Button value={false}>
                        <CloseOutlined /> False
                    </Radio.Button>
                </Radio.Group>
            )
        case 'date':
            return (
                <DatePicker
                    popupStyle={{ zIndex: 1061 }}
                    allowClear
                    placeholder="Choose a date"
                    className="retention-date-picker"
                    suffixIcon={null}
                    use12Hours
                    showTime
                    value={value ? moment(value) : null}
                    onChange={(date: moment.Moment | null) => onChange(date?.toISOString())}
                />
            )
    }
}
