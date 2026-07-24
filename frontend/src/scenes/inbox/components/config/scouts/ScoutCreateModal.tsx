import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { useId } from 'react'

import { LemonButton, LemonInput, LemonModal, LemonSelect, LemonSwitch, LemonTextArea } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'
import { teamLogic } from 'scenes/teamLogic'

import type { SignalScoutCreateResponseApi } from 'products/signals/frontend/generated/api.schemas'

import {
    ScoutCreateInitialValues,
    ScoutCreateModalLogicProps,
    scoutCreateModalLogic,
} from '../../../logics/scoutCreateModalLogic'
import {
    dailyCronToTime,
    DEFAULT_SCOUT_DAILY_TIME,
    getScoutScheduleMode,
    getScoutScheduleOptions,
    SCOUT_CUSTOM_CRON_SCHEDULE_MODE,
    SCOUT_DAILY_AT_SCHEDULE_MODE,
    SIGNALS_SCOUT_SKILL_PREFIX,
} from '../../../utils/scoutRunsWindow'

export interface ScoutCreateModalProps {
    isOpen: boolean
    onClose: () => void
    initialValues?: ScoutCreateInitialValues
    onCreated?: (scout: SignalScoutCreateResponseApi) => void
}

export function ScoutCreateModal({ isOpen, onClose, initialValues, onCreated }: ScoutCreateModalProps): JSX.Element {
    const logicKey = useId()
    const formId = `scout-create-form-${logicKey}`
    const logicProps: ScoutCreateModalLogicProps = { logicKey, initialValues, onClose, onCreated }
    const logic = scoutCreateModalLogic(logicProps)
    const { isScoutCreateFormSubmitting, scoutCreateForm, scoutCreateFormChanged, scoutCreateFormValidationErrors } =
        useValues(logic)
    const { resetScoutCreateForm, setScoutCreateDailyTime, setScoutCreateScheduleMode } = useActions(logic)
    const { timezone: projectTimezone } = useValues(teamLogic)
    const scheduleMode = getScoutScheduleMode(scoutCreateForm.config)
    const dailyTime = dailyCronToTime(scoutCreateForm.config.run_cron_schedule)

    const handleClose = (): void => {
        if (isScoutCreateFormSubmitting) {
            return
        }
        resetScoutCreateForm()
        onClose()
    }

    const firstError = [
        scoutCreateFormValidationErrors.name,
        scoutCreateFormValidationErrors.description,
        scoutCreateFormValidationErrors.body,
        scoutCreateFormValidationErrors.config?.run_interval_minutes,
    ].find((error): error is string => typeof error === 'string')

    return (
        <LemonModal
            isOpen={isOpen}
            onClose={handleClose}
            title="Create a scout"
            description="Define what the scout should investigate and how often it should run."
            width={720}
            hasUnsavedInput={scoutCreateFormChanged}
            footer={
                <>
                    <LemonButton
                        type="secondary"
                        disabledReason={isScoutCreateFormSubmitting ? 'Creating the scout' : undefined}
                        onClick={handleClose}
                    >
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        form={formId}
                        htmlType="submit"
                        loading={isScoutCreateFormSubmitting}
                        disabledReason={firstError}
                    >
                        Create scout
                    </LemonButton>
                </>
            }
        >
            <Form
                logic={scoutCreateModalLogic}
                props={logicProps}
                formKey="scoutCreateForm"
                id={formId}
                enableFormOnSubmit
            >
                <div className="flex flex-col gap-4">
                    <LemonField
                        name="name"
                        label="Name"
                        help={
                            <>
                                Scout names start with{' '}
                                <span className="font-mono text-[11px]">{SIGNALS_SCOUT_SKILL_PREFIX}</span>.
                            </>
                        }
                    >
                        <LemonInput
                            autoFocus
                            maxLength={64}
                            placeholder="signals-scout-checkout-failures"
                            data-attr="scout-create-name"
                        />
                    </LemonField>

                    <LemonField
                        name="description"
                        label="Description"
                        help="A short summary of the signal or behavior this scout investigates."
                    >
                        <LemonTextArea
                            minRows={2}
                            maxRows={4}
                            maxLength={4096}
                            placeholder="Investigates recurring checkout failures and reports meaningful changes."
                            data-attr="scout-create-description"
                        />
                    </LemonField>

                    <LemonField name="body" label="Instructions" help="This markdown prompt is executed on every run.">
                        <LemonTextArea
                            minRows={8}
                            maxRows={16}
                            className="font-mono text-xs"
                            placeholder="Describe the signals, thresholds, investigation steps, and reporting criteria."
                            data-attr="scout-create-instructions"
                        />
                    </LemonField>

                    <div className="flex flex-col gap-3 border-t border-primary pt-4">
                        <span className="font-medium text-sm">Run settings</span>
                        <LemonField.Pure
                            label="Schedule"
                            help={
                                scheduleMode === SCOUT_CUSTOM_CRON_SCHEDULE_MODE
                                    ? 'A cron schedule provided by the opening context'
                                    : 'Choose a rolling cadence, or a set time each day'
                            }
                        >
                            <LemonSelect
                                value={scheduleMode}
                                options={getScoutScheduleOptions(scoutCreateForm.config)}
                                onChange={setScoutCreateScheduleMode}
                            />
                        </LemonField.Pure>
                        {scheduleMode === SCOUT_DAILY_AT_SCHEDULE_MODE ? (
                            <LemonField.Pure label="Run time" help={`Uses the project timezone (${projectTimezone})`}>
                                <LemonInput
                                    key={scoutCreateForm.config.run_cron_schedule ?? 'unset'}
                                    type="time"
                                    step={60}
                                    defaultValue={dailyTime ?? DEFAULT_SCOUT_DAILY_TIME}
                                    onBlur={(event) => {
                                        if (event.currentTarget.value) {
                                            setScoutCreateDailyTime(event.currentTarget.value)
                                        }
                                    }}
                                />
                            </LemonField.Pure>
                        ) : null}
                        <LemonField name="config.enabled">
                            {({ value, onChange }) => (
                                <LemonSwitch
                                    checked={value}
                                    onChange={onChange}
                                    label="Enable this scout"
                                    bordered
                                    fullWidth
                                />
                            )}
                        </LemonField>
                        <LemonField name="config.emit">
                            {({ value, onChange }) => (
                                <LemonSwitch
                                    checked={value}
                                    onChange={onChange}
                                    label="Write findings to the inbox"
                                    bordered
                                    fullWidth
                                />
                            )}
                        </LemonField>
                        <span className="text-xs text-muted">
                            Turn off inbox findings to run the scout in dry-run mode.
                        </span>
                    </div>
                </div>
            </Form>
        </LemonModal>
    )
}
