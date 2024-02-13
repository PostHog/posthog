import { IconCheck } from '@posthog/icons'
import { LemonSegmentedButton, Tooltip } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { ChildFunctionProps, Form } from 'kea-forms'
import { CodeEditor } from 'lib/components/CodeEditors'
import { DatePicker } from 'lib/components/DatePicker'
import { dayjs } from 'lib/dayjs'
import { IconClose, IconPlayCircle, IconSettings } from 'lib/lemon-ui/icons'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonCalendarRangeInline } from 'lib/lemon-ui/LemonCalendarRange/LemonCalendarRangeInline'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInput } from 'lib/lemon-ui/LemonInput/LemonInput'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { formatDate, formatDateRange } from 'lib/utils'
import { useMemo } from 'react'
import { userLogic } from 'scenes/userLogic'

import { JobPayloadFieldOptions } from '~/types'

import { interfaceJobsLogic, InterfaceJobsProps } from './interfaceJobsLogic'

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
                        <IconPlayCircle
                            className={runJobAvailable ? 'Plugin__RunJobButton' : 'Plugin__RunJobButton--disabled'}
                        />
                    ) : (
                        <IconSettings
                            className={runJobAvailable ? 'Plugin__RunJobButton' : 'Plugin__RunJobButton--disabled'}
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
                        <LemonField name={key} label={options.title || key} key={key} className="mb-4">
                            {(props) => <FieldInput options={options} {...props} />}
                        </LemonField>
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
            return <LemonInput type="number" value={value} onChange={onChange} />
        case 'json':
            return (
                <CodeEditor
                    options={{ codeLens: false, lineNumbers: 'off' }}
                    className="Plugin__JobJsonEditor"
                    language="json"
                    height={200}
                    value={value}
                    onChange={onChange}
                />
            )
        case 'boolean':
            return (
                <LemonSegmentedButton
                    onChange={onChange}
                    value={value}
                    options={[
                        {
                            value: true,
                            label: 'True',
                            icon: <IconCheck />,
                        },
                        {
                            value: false,
                            label: 'False',
                            icon: <IconClose />,
                        },
                    ]}
                />
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
                    value={value ? dayjs(value) : null}
                    onChange={(date) => onChange(date?.toISOString())}
                />
            )
        case 'daterange':
            return (
                <div className="border rounded p-4">
                    <div className="pb-4">
                        <LemonCalendarRangeInline
                            value={value ? [dayjs(value[0]), dayjs(value[1])] : null}
                            onChange={([rangeStart, rangeEnd]) =>
                                onChange([rangeStart.format('YYYY-MM-DD'), rangeEnd.format('YYYY-MM-DD')])
                            }
                        />
                    </div>
                    <div className="border-t pt-4">
                        <span className="text-muted">Selected period:</span>{' '}
                        {value ? (
                            <span>
                                {value[0] === value[1]
                                    ? formatDate(dayjs(value[0]))
                                    : formatDateRange(dayjs(value[0]), dayjs(value[1]))}
                            </span>
                        ) : (
                            <span className="italic">No period selected.</span>
                        )}
                    </div>
                </div>
            )
    }
}
