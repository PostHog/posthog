import { LemonInput } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { IconChevronLeft } from 'lib/lemon-ui/icons'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonModal } from 'lib/lemon-ui/LemonModal'

import { InsightShortId } from '~/types'

import { alertLogic } from '../alertLogic'
import { alertsLogic } from '../alertsLogic'

interface EditAlertProps {
    id: number | 'new'
    insightShortId: InsightShortId
    onCancel: () => void
    onDelete: () => void
}

export function EditAlert({ id, insightShortId, onCancel, onDelete }: EditAlertProps): JSX.Element {
    const logicProps = {
        id,
        insightShortId,
    }
    const logic = alertLogic(logicProps)
    const alertslogic = alertsLogic({
        id,
        insightShortId,
    })

    const { alert, isAlertSubmitting, alertChanged } = useValues(logic)
    const { deleteAlert } = useActions(alertslogic)

    const _onDelete = (): void => {
        if (id !== 'new') {
            deleteAlert(id)
            onDelete()
        }
    }

    return (
        <Form logic={alertLogic} props={logicProps} formKey="alert" enableFormOnSubmit className="LemonModal__layout">
            <LemonModal.Header>
                <div className="flex items-center gap-2">
                    <LemonButton icon={<IconChevronLeft />} onClick={onCancel} size="xsmall" />

                    <h3>{id === 'new' ? 'New' : 'Edit '} Alert</h3>
                </div>
            </LemonModal.Header>

            <LemonModal.Content className="space-y-2">
                {!alert ? (
                    <div className="p-4 text-center">
                        <h2>Not found</h2>
                        <p>This alert could not be found. It may have been deleted.</p>
                    </div>
                ) : (
                    <>
                        <LemonField name="name" label="Name">
                            <LemonInput placeholder="e.g. High error rate" />
                        </LemonField>

                        <LemonField
                            name="target_value"
                            label="Who do you want to notify about anomalies"
                            help="Enter comma separated email addresses of the users you want notify about anomalies"
                        >
                            <LemonInput data-attr="alert-emails" placeholder="Enter an email address" />
                        </LemonField>
                        <LemonField name="anomaly_condition" label="Anomaly condition">
                            {({ value, onChange }) => (
                                <span className="flex gap-10">
                                    <div>
                                        Lower threshold
                                        <LemonInput
                                            type="number"
                                            className="w-20"
                                            value={value?.absolute_threshold?.lower}
                                            onChange={(newLower) => {
                                                const newValue = { ...value }
                                                if (!newValue.absolute_threshold) {
                                                    newValue.absolute_threshold = {}
                                                }
                                                newValue.absolute_threshold.lower = newLower
                                                onChange(newValue)
                                            }}
                                        />
                                    </div>
                                    <div>
                                        Upper threshold
                                        <LemonInput
                                            type="number"
                                            className="w-20"
                                            value={value?.absolute_threshold?.upper}
                                            onChange={(newUpper) => {
                                                const newValue = { ...value }
                                                if (!newValue.absolute_threshold) {
                                                    newValue.absolute_threshold = {}
                                                }
                                                newValue.absolute_threshold.upper = newUpper
                                                onChange(newValue)
                                            }}
                                        />
                                    </div>
                                </span>
                            )}
                        </LemonField>
                    </>
                )}
            </LemonModal.Content>

            <LemonModal.Footer>
                <div className="flex-1">
                    {alert && id !== 'new' && (
                        <LemonButton type="secondary" status="danger" onClick={_onDelete}>
                            Delete alert
                        </LemonButton>
                    )}
                </div>
                <LemonButton type="secondary" onClick={onCancel}>
                    Cancel
                </LemonButton>
                <LemonButton type="primary" htmlType="submit" loading={isAlertSubmitting} disabled={!alertChanged}>
                    {id === 'new' ? 'Create alert' : 'Save'}
                </LemonButton>
            </LemonModal.Footer>
        </Form>
    )
}
