import { useMemo } from 'react'
import { PlayCircleOutlined, CheckOutlined, CloseOutlined, SettingOutlined } from '@ant-design/icons'
import { Tooltip, Radio, InputNumber, DatePicker } from 'antd'
import { ChildFunctionProps, Form } from 'kea-forms'
import { Field } from 'lib/forms/Field'
import MonacoEditor from '@monaco-editor/react'
import { useValues, useActions } from 'kea'
import { userLogic } from 'scenes/userLogic'
import { JobPayloadFieldOptions } from '~/types'
import { interfaceJobsLogic, InterfaceJobsProps } from './interfaceJobsLogic'
import { LemonInput } from 'lib/components/LemonInput/LemonInput'
import moment from 'moment'
import { LemonModal } from 'lib/components/LemonModal'
import { LemonButton } from 'lib/components/LemonButton'
import { LemonCalendarRangeInline } from 'lib/components/LemonCalendarRange/LemonCalendarRangeInline'

// keep in sync with plugin-server's export-historical-events.ts
export const HISTORICAL_EXPORT_JOB_NAME = 'Export historical events'
export const HISTORICAL_EXPORT_JOB_NAME_V2 = 'Export historical events V2'

export function PluginJobConfiguration(props: InterfaceJobsProps): JSX.Element {
    const { jobName, jobSpec, pluginConfigId, pluginId } = props
    const { playButtonOnClick } = useActions(interfaceJobsLogic(props))
    const { runJobAvailable } = useValues(interfaceJobsLogic(props))

    const jobHasEmptyPayload = Object.keys(jobSpec.payload || {}).length === 0

    const configureOrRunJobTooltip = runJobAvailable
        ? jobHasEmptyPayload
            ? `Run job`
            : `Configure and run job`
        : `You already ran this job recently.`

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

            <PluginJobModal jobName={jobName} jobSpec={jobSpec} pluginConfigId={pluginConfigId} pluginId={pluginId} />
        </>
    )
}

export function PluginJobModal(props: InterfaceJobsProps): JSX.Element {
    const { jobName, jobSpec } = props
    const { setIsJobModalOpen, submitJobPayload } = useActions(interfaceJobsLogic(props))
    const { isJobModalOpen } = useValues(interfaceJobsLogic(props))
    const { user } = useValues(userLogic)

    const shownFields = useMemo(() => {
        return Object.entries(jobSpec.payload || {})
            .filter(([, options]) => !options.staff_only || user?.is_staff || user?.is_impersonated)
            .sort((a, b) => a[0].localeCompare(b[0]))
    }, [jobSpec, user])

    return (
        <LemonModal
            isOpen={isJobModalOpen}
            onClose={() => setIsJobModalOpen(false)}
            title={`Configuring job '${jobName}'`}
            footer={
                <>
                    <LemonButton type="secondary" className="mr-2" onClick={() => setIsJobModalOpen(false)}>
                        Cancel
                    </LemonButton>
                    <LemonButton data-attr="run-job" type="primary" onClick={() => submitJobPayload()}>
                        Run job now
                    </LemonButton>
                </>
            }
        >
            {shownFields.length > 0 ? (
                <Form logic={interfaceJobsLogic} props={props} formKey="jobPayload">
                    {shownFields.map(([key, options]) => (
                        <Field name={key} label={options.title || key} key={key} className="mb-4">
                            {(props) => <FieldInput options={options} {...props} />}
                        </Field>
                    ))}
                </Form>
            ) : null}
        </LemonModal>
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
        case 'daterange':
            return <LemonCalendarRangeInline value={value || null} onChange={onChange} />
    }
}
