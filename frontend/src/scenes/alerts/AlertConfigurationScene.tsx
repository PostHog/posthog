import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { router } from 'kea-router'
import { useEffect } from 'react'

import { IconArrowLeft } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonCheckbox, LemonInput, LemonSelect, LemonSkeleton, Spinner } from '@posthog/lemon-ui'

import { MemberSelectMultiple } from 'lib/components/MemberSelectMultiple'
import { PageHeader } from 'lib/components/PageHeader'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { AlertStateIndicator } from 'lib/components/Alerts/views/ManageAlertsModal'
import { DetectorBuilder, createDefaultDetectorsConfig } from 'lib/components/Alerts/detectors'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneDivider } from '~/layout/scenes/components/SceneDivider'
import { SceneSection } from '~/layout/scenes/components/SceneSection'
import { AlertCalculationInterval } from '~/queries/schema/schema-general'
import { urls } from 'scenes/urls'

import { alertConfigurationSceneLogic } from './alertConfigurationSceneLogic'

export interface AlertConfigurationSceneProps {
    alertId?: string
    insightId?: string
}

export function AlertConfigurationScene({ alertId, insightId }: AlertConfigurationSceneProps): JSX.Element {
    const logicProps = { alertId, insightId }
    const logic = alertConfigurationSceneLogic(logicProps)
    const {
        alert,
        alertLoading,
        insight,
        insightLoading,
        isNew,
        alertFormValues,
        isAlertFormSubmitting,
    } = useValues(logic)
    const { loadAlert, loadInsight, setAlertFormValue, submitAlertForm, deleteAlert } = useActions(logic)

    useEffect(() => {
        if (alertId) {
            loadAlert()
        }
        if (insightId) {
            loadInsight()
        }
    }, [alertId, insightId])

    if (alertLoading || insightLoading) {
        return (
            <SceneContent>
                <div className="flex items-center justify-center min-h-[400px]">
                    <Spinner className="text-4xl" />
                </div>
            </SceneContent>
        )
    }

    const handleBack = (): void => {
        if (insight) {
            router.actions.push(urls.insightView(insight.short_id))
        } else {
            router.actions.push(urls.savedInsights())
        }
    }

    return (
        <SceneContent>
            <PageHeader
                buttons={
                    <div className="flex gap-2">
                        <LemonButton onClick={handleBack} icon={<IconArrowLeft />}>
                            Back to insight
                        </LemonButton>
                    </div>
                }
            />

            <Form logic={alertConfigurationSceneLogic} props={logicProps} formKey="alertForm">
                <div className="space-y-6">
                    {/* Header Section */}
                    <SceneSection
                        title={isNew ? 'Create alert' : 'Edit alert'}
                        subtitle={insight ? `For insight: ${insight.name || 'Untitled'}` : undefined}
                    >
                        {!isNew && alert && (
                            <div className="flex items-center gap-2 mb-4">
                                <span className="text-muted">Status:</span>
                                <AlertStateIndicator alert={alert} />
                            </div>
                        )}

                        <div className="space-y-4">
                            <LemonField name="name" label="Alert name">
                                <LemonInput placeholder="My alert" />
                            </LemonField>

                            <LemonField name="enabled" label="Enabled">
                                <LemonCheckbox
                                    checked={alertFormValues.enabled}
                                    onChange={(checked) => setAlertFormValue('enabled', checked)}
                                    label="Alert is active"
                                />
                            </LemonField>
                        </div>
                    </SceneSection>

                    <SceneDivider />

                    {/* Detectors Section */}
                    <SceneSection
                        title="Detection rules"
                        subtitle="Configure when this alert should trigger using one or more detectors"
                    >
                        <DetectorBuilder
                            config={alertFormValues.detectors}
                            onChange={(detectors) => setAlertFormValue('detectors', detectors)}
                        />
                    </SceneSection>

                    <SceneDivider />

                    {/* Schedule Section */}
                    <SceneSection title="Schedule" subtitle="How often should this alert be checked?">
                        <div className="space-y-4">
                            <LemonField name="calculation_interval" label="Check frequency">
                                <LemonSelect
                                    value={alertFormValues.calculation_interval}
                                    onChange={(value) => setAlertFormValue('calculation_interval', value)}
                                    options={[
                                        { value: AlertCalculationInterval.HOURLY, label: 'Hourly' },
                                        { value: AlertCalculationInterval.DAILY, label: 'Daily' },
                                        { value: AlertCalculationInterval.WEEKLY, label: 'Weekly' },
                                        { value: AlertCalculationInterval.MONTHLY, label: 'Monthly' },
                                    ]}
                                />
                            </LemonField>

                            <LemonField name="skip_weekend">
                                <LemonCheckbox
                                    checked={alertFormValues.skip_weekend}
                                    onChange={(checked) => setAlertFormValue('skip_weekend', checked)}
                                    label="Skip weekend checks"
                                />
                            </LemonField>
                        </div>
                    </SceneSection>

                    <SceneDivider />

                    {/* Notifications Section */}
                    <SceneSection title="Notifications" subtitle="Who should be notified when this alert fires?">
                        <LemonField name="subscribed_users" label="Notify these users">
                            <MemberSelectMultiple
                                value={alertFormValues.subscribed_users || []}
                                onChange={(value) => setAlertFormValue('subscribed_users', value)}
                            />
                        </LemonField>
                    </SceneSection>

                    <SceneDivider />

                    {/* Actions */}
                    <div className="flex justify-between items-center">
                        <div>
                            {!isNew && (
                                <LemonButton status="danger" type="secondary" onClick={deleteAlert}>
                                    Delete alert
                                </LemonButton>
                            )}
                        </div>
                        <div className="flex gap-2">
                            <LemonButton onClick={handleBack}>Cancel</LemonButton>
                            <LemonButton
                                type="primary"
                                htmlType="submit"
                                loading={isAlertFormSubmitting}
                                onClick={submitAlertForm}
                            >
                                {isNew ? 'Create alert' : 'Save changes'}
                            </LemonButton>
                        </div>
                    </div>
                </div>
            </Form>
        </SceneContent>
    )
}
