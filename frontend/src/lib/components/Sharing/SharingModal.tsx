import React from 'react'
import { LemonModal } from 'lib/components/LemonModal'
import { SharingBaseProps } from './utils'
import { InsightModel, InsightShortId, InsightType } from '~/types'
import { useActions, useValues } from 'kea'
import { sharingLogic } from './sharingLogic'
import { Skeleton } from 'antd'
import { LemonButton, LemonCheckbox, LemonSwitch } from '@posthog/lemon-ui'
import { copyToClipboard } from 'lib/utils'
import { IconCopy, IconLock } from '../icons'
import { CodeSnippet, Language } from 'scenes/ingestion/frameworks/CodeSnippet'
import { DashboardCollaboration } from 'scenes/dashboard/DashboardCollaborators'
import { Field } from 'lib/forms/Field'
import { Tooltip } from 'lib/components/Tooltip'
import './SharingModal.scss'
import { Form } from 'kea-forms'

export interface SharingModalProps extends SharingBaseProps {
    dashboardId?: number
    insightShortId?: InsightShortId
    insight?: Partial<InsightModel>
    visible: boolean
    closeModal: () => void
}

export function Sharing({ dashboardId, insightShortId, insight }: SharingModalProps): JSX.Element {
    const logicProps = {
        dashboardId,
        insightShortId,
    }
    const {
        whitelabelAvailable,
        sharingConfiguration,
        sharingConfigurationLoading,
        embedCode,
        iframeProperties,
        shareLink,
    } = useValues(sharingLogic(logicProps))
    const { setIsEnabled } = useActions(sharingLogic(logicProps))

    const showNoLabelCheckbox = insight?.filters?.insight === InsightType.TRENDS
    const resource = dashboardId ? 'dashboard' : 'insight'

    return (
        <div>
            {dashboardId ? (
                <div className="mb">
                    <h4>Collaboration settings</h4>
                    <DashboardCollaboration dashboardId={dashboardId} />
                </div>
            ) : undefined}

            <h4>Share or embed {resource}</h4>

            <div>
                {!sharingConfiguration && sharingConfigurationLoading ? (
                    <Skeleton />
                ) : !sharingConfiguration ? (
                    <p>Something went wrong...</p>
                ) : (
                    <div className="space-y-05">
                        <LemonSwitch
                            id="sharing-switch"
                            label={`Share ${resource} publicly`}
                            checked={sharingConfiguration.enabled}
                            loading={sharingConfigurationLoading}
                            data-attr="sharing-switch"
                            onChange={(active) => {
                                setIsEnabled(active)
                            }}
                            fullWidth
                            type="primary"
                            style={{ padding: '0.5rem 1rem' }}
                        />

                        {sharingConfiguration.enabled ? (
                            <>
                                {sharingConfiguration.access_token && (
                                    <LemonButton
                                        data-attr="sharing-link-button"
                                        type="secondary"
                                        onClick={() => copyToClipboard(shareLink, 'link')}
                                        icon={<IconCopy />}
                                        fullWidth
                                        style={{ padding: '0.5rem 1rem' }}
                                    >
                                        Copy shared {resource} link
                                    </LemonButton>
                                )}
                                <div>Use this HTML snippet to embed the {resource} on your website:</div>

                                <CodeSnippet wrap={true} language={Language.HTML}>
                                    {embedCode}
                                </CodeSnippet>
                                <Form logic={sharingLogic} props={logicProps} formKey="embedConfig" className="flex">
                                    <Field name="whitelabel" noStyle>
                                        {({ value, onChange }) => (
                                            <LemonCheckbox
                                                label={
                                                    <>
                                                        <span className="mr-05">Show Logo</span>
                                                        {!whitelabelAvailable ? (
                                                            <Tooltip title="Upgrade to an enterprise plan to hide the logo">
                                                                <IconLock />
                                                            </Tooltip>
                                                        ) : null}
                                                    </>
                                                }
                                                onChange={() => onChange(!value)}
                                                rowProps={{ fullWidth: true }}
                                                checked={!value}
                                                disabled={!whitelabelAvailable}
                                            />
                                        )}
                                    </Field>
                                    {showNoLabelCheckbox && (
                                        <Field name="noLegend" noStyle>
                                            {({ value, onChange }) => (
                                                <LemonCheckbox
                                                    label={<div>Show Legend</div>}
                                                    onChange={() => onChange(!value)}
                                                    rowProps={{ fullWidth: true }}
                                                    checked={!value}
                                                />
                                            )}
                                        </Field>
                                    )}
                                </Form>
                                {insight && (
                                    <div className="SharingPreview">
                                        <h5 className="mb-05">PREVIEW</h5>
                                        <iframe style={{ display: 'block' }} {...iframeProperties} />
                                    </div>
                                )}
                            </>
                        ) : null}
                    </div>
                )}
            </div>
        </div>
    )
}

export function SharingModal(props: SharingModalProps): JSX.Element {
    const { visible, closeModal } = props

    return (
        <>
            <LemonModal onCancel={closeModal} afterClose={closeModal} visible={visible} width={650}>
                <Sharing {...props} />
            </LemonModal>
        </>
    )
}
