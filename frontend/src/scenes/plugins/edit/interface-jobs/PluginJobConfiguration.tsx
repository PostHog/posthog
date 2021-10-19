import React from 'react'
import { PlayCircleOutlined, CheckOutlined, CloseOutlined, SettingOutlined } from '@ant-design/icons'
import { Tooltip, Form, Input, Radio, InputNumber, DatePicker } from 'antd'
import Modal from 'antd/lib/modal/Modal'
import MonacoEditor from '@monaco-editor/react'
import { useValues, useActions } from 'kea'
import { JobSpec } from '~/types'
import { validateJsonFormItem } from 'lib/utils'
import { interfaceJobsLogic } from './interfaceJobsLogic'

interface PluginJobConfigurationProps {
    jobName: string
    jobSpec: JobSpec
    pluginConfigId: number
    pluginId: number
}

const requiredRule = {
    required: true,
    message: 'Please enter a value!',
}

// keep in sync with plugin-server's export-historical-events.ts
const HISTORICAL_EXPORT_JOB_NAME = 'Export historical events'

export function PluginJobConfiguration({
    jobName,
    jobSpec,
    pluginConfigId,
    pluginId,
}: PluginJobConfigurationProps): JSX.Element {
    if (jobName === HISTORICAL_EXPORT_JOB_NAME) {
        jobSpec.payload = {
            dateFrom: { type: 'date' },
            dateTo: { type: 'date' },
        }
    }

    const logicProps = { jobName, pluginConfigId, pluginId, jobSpecPayload: jobSpec.payload }
    const { setIsJobModalOpen, runJob, playButtonOnClick } = useActions(interfaceJobsLogic(logicProps))
    const { runJobAvailable, isJobModalOpen } = useValues(interfaceJobsLogic(logicProps))

    const jobHasEmptyPayload = Object.keys(jobSpec.payload || {}).length === 0

    const [form] = Form.useForm()

    const configureOrRunJobTooltip = runJobAvailable
        ? jobHasEmptyPayload
            ? `Run job`
            : `Configure and run job`
        : `You already ran this job recently.`

    return (
        <>
            <span
                style={{
                    marginLeft: 10,
                    marginRight: 5,
                }}
                onClick={() => playButtonOnClick(form, jobHasEmptyPayload)}
            >
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
                onOk={() => runJob(form)}
                okText={'Run job now'}
                title={`Configuring job '${jobName}'`}
            >
                {jobSpec.payload ? (
                    <Form form={form} layout="vertical">
                        {Object.entries(jobSpec.payload).map(([key, options]) => (
                            <span key={key}>
                                <Form.Item
                                    style={{ marginBottom: 15 }}
                                    name={key}
                                    required={!!options.required}
                                    rules={
                                        options.required
                                            ? [
                                                  requiredRule,
                                                  ...(options.type === 'json'
                                                      ? [{ validator: validateJsonFormItem }]
                                                      : []),
                                              ]
                                            : []
                                    }
                                    label={key}
                                >
                                    {options.type === 'string' ? (
                                        <Input />
                                    ) : options.type === 'number' ? (
                                        <InputNumber />
                                    ) : options.type === 'json' ? (
                                        <MonacoEditor
                                            options={{ codeLens: false }}
                                            className="plugin-job-json-editor"
                                            language="json"
                                            height={200}
                                        />
                                    ) : options.type === 'boolean' ? (
                                        <Radio.Group id="propertyValue" buttonStyle="solid">
                                            <Radio.Button value={true} defaultChecked>
                                                <CheckOutlined /> True
                                            </Radio.Button>
                                            <Radio.Button value={false}>
                                                <CloseOutlined /> False
                                            </Radio.Button>
                                        </Radio.Group>
                                    ) : options.type === 'date' ? (
                                        <DatePicker
                                            popupStyle={{ zIndex: 1061 }}
                                            allowClear
                                            placeholder="Today"
                                            className="retention-date-picker"
                                            suffixIcon={null}
                                            use12Hours
                                            showTime
                                        />
                                    ) : null}
                                </Form.Item>
                            </span>
                        ))}
                    </Form>
                ) : null}
            </Modal>
        </>
    )
}
