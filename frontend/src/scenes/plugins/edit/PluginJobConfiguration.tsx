import React, { useState } from 'react'
import { PlayCircleOutlined, CheckOutlined, CloseOutlined } from '@ant-design/icons'
import { Tooltip, Form, Input, Radio, InputNumber } from 'antd'
import Modal from 'antd/lib/modal/Modal'
import MonacoEditor from '@monaco-editor/react'
import api from 'lib/api'
import { JobSpec } from '~/types'
import { toast } from 'react-toastify'
import { errorToast, validateJsonFormItem } from 'lib/utils'

interface PluginJobConfigurationProps {
    jobName: string
    jobSpec: JobSpec
    pluginConfigId: number
}

const requiredRule = {
    required: true,
    message: 'Please enter a value!',
}

export function PluginJobConfiguration({ jobName, jobSpec, pluginConfigId }: PluginJobConfigurationProps): JSX.Element {
    const [isJobModalOpen, setIsJobModalOpen] = useState(false)
    const [runJobAvailable, setRunJobAvailable] = useState(true)

    const [form] = Form.useForm()

    const jobHasEmptyPayload = Object.keys(jobSpec.payload || {}).length === 0

    const runJob = async (): Promise<void> => {
        try {
            await form.validateFields()
        } catch {
            return
        }

        setIsJobModalOpen(false)

        try {
            await api.create(`api/plugin_config/${pluginConfigId}/job`, {
                job: {
                    type: jobName,
                    payload: form.getFieldsValue(),
                },
            })
        } catch (error) {
            errorToast(`Enqueuing job '${jobName}' failed`)
            return
        }

        // temporary handling to prevent people from rage
        // clicking and creating multiple jobs - this will be
        // subsituted by better feedback tools like progress bars
        setRunJobAvailable(false)
        setTimeout(() => {
            setRunJobAvailable(true)
        }, 15000)
        toast.success('Job enqueued succesfully.')
    }

    const playButtonOnClick = (): void => {
        if (runJobAvailable) {
            if (jobHasEmptyPayload) {
                runJob()
                return
            }
            setIsJobModalOpen(true)
        }
    }

    const playCircleTooltip = runJobAvailable
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
                onClick={playButtonOnClick}
            >
                <Tooltip title={playCircleTooltip}>
                    <PlayCircleOutlined
                        className={runJobAvailable ? 'plugin-run-job-button' : 'plugin-run-job-button-disabled'}
                    />
                </Tooltip>
            </span>

            <Modal
                visible={isJobModalOpen}
                onCancel={() => setIsJobModalOpen(false)}
                onOk={async () => await runJob()}
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
