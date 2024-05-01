import { IconInfo, IconTrash } from '@posthog/icons'
import { LemonButton, LemonSelect, Tooltip } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInputSelect } from 'lib/lemon-ui/LemonInputSelect/LemonInputSelect'
import { useEffect } from 'react'
import { membersLogic } from 'scenes/organization/membersLogic'

import {
    ExperimentFinishAction,
    ExperimentFinishActionEmailValue,
    ExperimentFinishActionType,
    ExperimentFinishEmailTypes,
} from '~/types'

import { ON_FINISH_EXPERIMENT_ACTIONS } from './constants'
import { experimentLogic } from './experimentLogic'

export function AddNewExperimentFinishAction(): JSX.Element {
    const { experiment } = useValues(experimentLogic)
    const { addOnFinishExperimentAction } = useActions(experimentLogic)

    return (
        <div className="mb-2 mt-4">
            <LemonButton
                data-attr="experiment-add-actions"
                type="secondary"
                onClick={() => {
                    addOnFinishExperimentAction()
                }}
                disabledReason={
                    experiment.finish_actions?.length === ON_FINISH_EXPERIMENT_ACTIONS.length
                        ? 'There are no more supported actions at present.'
                        : false
                }
            >
                Add Action
            </LemonButton>
        </div>
    )
}

function ExperimentFinishEmailRenderer({
    emailParticipants,
    label,
    tooltip,
}: {
    emailParticipants: string[] | undefined
    label: string
    tooltip: string
}): JSX.Element {
    if (!emailParticipants || emailParticipants.length === 0) {
        return <></>
    }

    return (
        <div className="flex items-center mt-2">
            <span className="mr-2 label-width">{label}</span>
            <LemonInputSelect
                mode="multiple"
                disabled
                options={emailParticipants.map((email) => ({
                    key: email,
                    label: email,
                }))}
                value={emailParticipants}
                className="LemonInputSelect input-width"
            />
            <Tooltip title={tooltip}>
                <IconInfo className="ml-1 text-muted text-xl" />
            </Tooltip>
        </div>
    )
}

export function ExperimentFinishEmailOverviewRenderer({
    finishAction,
}: {
    finishAction: ExperimentFinishAction
}): JSX.Element {
    const allEmailParticipants = finishAction.value?.ALL
    const successEmailParticipants = finishAction.value?.SUCCESS
    const failureEmailParticipants = finishAction.value?.FAILURE

    return (
        <div key={finishAction.action} className="mt-2">
            We will send an email to:
            <ExperimentFinishEmailRenderer
                label="All these members:"
                tooltip="All members will receive the email, regardless of the outcome"
                emailParticipants={allEmailParticipants}
            />
            <ExperimentFinishEmailRenderer
                tooltip="If the experiment results are statistically significant, & the experiment succeeded, these members will receive the email"
                label="If it was successful:"
                emailParticipants={successEmailParticipants}
            />
            <ExperimentFinishEmailRenderer
                label="If it failed:"
                tooltip="If the experiment results are NOT statistically significant, or the experiment failed, these members will receive the email"
                emailParticipants={failureEmailParticipants}
            />
        </div>
    )
}

function ExperimentSendEmailToLemonInput({
    onChange,
    value,
}: {
    onChange: (newValue: string[]) => void
    value: string[] | undefined
}): JSX.Element {
    const { members } = useValues(membersLogic)

    return (
        <LemonInputSelect
            placeholder="Enter email addresses"
            mode="multiple"
            onChange={onChange}
            options={members?.map((member) => ({
                key: member.user.email,
                label: member.user.email,
            }))}
            value={value}
            allowCustomValues
        />
    )
}

export function ExperimentFinishEmailActionTypeRenderer({
    finishAction,
}: {
    finishAction: ExperimentFinishAction
}): JSX.Element {
    const { action } = finishAction
    const values = finishAction.value as ExperimentFinishActionEmailValue | undefined

    const { addOnFinishActionEmails, removeOnFinishExperimentAction } = useActions(experimentLogic)

    useEffect(() => {
        membersLogic.actions.loadAllMembers()
    }, [])

    return (
        <div>
            <div className="flex items-center mb-4">
                <LemonSelect options={ON_FINISH_EXPERIMENT_ACTIONS} value={finishAction.action} />
                <span className="ml-2 mr-2">to </span>
                <LemonField name="experiment-finish-email-to">
                    <ExperimentSendEmailToLemonInput
                        onChange={(newValue: string[]) => {
                            addOnFinishActionEmails(ExperimentFinishEmailTypes.ALL, newValue)
                        }}
                        value={values?.ALL}
                    />
                </LemonField>
                <LemonButton icon={<IconTrash />} size="small" onClick={() => removeOnFinishExperimentAction(action)} />
            </div>
            Additionally,
            <div className="experiment-success mt-1">
                <span>If the experiment is a success, send this to: </span>
                <LemonField name="experiment-finish-email-success">
                    <ExperimentSendEmailToLemonInput
                        onChange={(newValue: string[]) => {
                            addOnFinishActionEmails(ExperimentFinishEmailTypes.SUCCESS, newValue)
                        }}
                        value={values?.SUCCESS}
                    />
                </LemonField>
            </div>
            <div className="experiment-failure mt-2">
                <span>If the experiment is a failure, send this to: </span>
                <LemonField name="experiment-finish-email-failure">
                    <ExperimentSendEmailToLemonInput
                        onChange={(newValue: string[]) => {
                            addOnFinishActionEmails(ExperimentFinishEmailTypes.FAILURE, newValue)
                        }}
                        value={values?.FAILURE}
                    />
                </LemonField>
            </div>
        </div>
    )
}

export function ExperimentFinishActionTypeRenderer({
    finishAction,
}: {
    finishAction: ExperimentFinishAction
}): JSX.Element {
    switch (finishAction.action) {
        case ExperimentFinishActionType.SEND_EMAIL:
            return <ExperimentFinishEmailActionTypeRenderer finishAction={finishAction} />
        default:
            return <div>Unknown action type</div>
    }
}
