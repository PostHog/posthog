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
import { VerticalForm } from 'lib/forms/VerticalForm'
import { Field } from 'lib/forms/Field'
import { Tooltip } from 'lib/components/Tooltip'

export interface SharingModalProps extends SharingBaseProps {
    dashboardId?: number
    insightShortId?: InsightShortId
    insight?: Partial<InsightModel>
    visible: boolean
    closeModal: () => void
}

export function Sharing({ dashboardId, insightShortId, insight }: SharingModalProps): JSX.Element {
    const logic = sharingLogic({
        dashboardId,
        insightShortId,
    })
    const {
        whitelabelAvailable,
        sharingConfiguration,
        sharingConfigurationLoading,
        embedCode,
        iframeProperties,
        shareLink,
    } = useValues(logic)
    const { setIsEnabled } = useActions(logic)

    const showNoLabelCheckbox = insight?.filters?.insight === InsightType.TRENDS
    const name = insight?.name || insight?.derived_name
    const resource = dashboardId ? 'dashboard' : 'insight'

    return (
        <>
            <header className="border-bottom pb-05">
                <h4 className="mt-05">
                    Share or embed {resource}
                    {name ? ` ${name}` : ''}
                </h4>
            </header>

            <section>
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
                                console.log('CHANGED', active)
                                setIsEnabled(active)
                                // setIsSharedDashboard(dashboard.id, active)
                            }}
                            type="primary"
                            style={{ width: '100%', height: '3rem', fontWeight: 600 }}
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
                                    >
                                        Copy shared {resource} link
                                    </LemonButton>
                                )}
                                <div>Use this HTML snippet to embed the {resource} on your website:</div>

                                <CodeSnippet wrap={true} language={Language.HTML}>
                                    {embedCode}
                                </CodeSnippet>
                                <VerticalForm
                                    logic={sharingLogic}
                                    props={{ insightShortId }}
                                    formKey="embedConfig"
                                    className="SharingModal-form"
                                >
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
                                </VerticalForm>
                                <iframe style={{ display: 'block' }} {...iframeProperties} />
                            </>
                        ) : null}
                    </div>
                )}
            </section>
        </>
    )
}

export function SharingModal(props: SharingModalProps): JSX.Element {
    const { visible, closeModal } = props

    return (
        <>
            <LemonModal onCancel={closeModal} afterClose={closeModal} visible={visible}>
                <Sharing {...props} />
            </LemonModal>
        </>
    )
}
