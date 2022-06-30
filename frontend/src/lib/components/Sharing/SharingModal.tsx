import React, { useEffect, useState } from 'react'
import { LemonModal } from 'lib/components/LemonModal'
import { InsightModel, InsightShortId, InsightType } from '~/types'
import { useActions, useValues } from 'kea'
import { sharingLogic } from './sharingLogic'
import { Skeleton } from 'antd'
import { LemonButton, LemonDivider, LemonSwitch } from '@posthog/lemon-ui'
import { copyToClipboard } from 'lib/utils'
import { IconGlobeLock, IconInfo, IconLink, IconLock, IconUnfoldLess, IconUnfoldMore } from '../icons'
import { CodeSnippet, Language } from 'scenes/ingestion/frameworks/CodeSnippet'
import { DashboardCollaboration } from 'scenes/dashboard/DashboardCollaborators'
import { Field } from 'lib/forms/Field'
import { Tooltip } from 'lib/components/Tooltip'
import './SharingModal.scss'
import { Form } from 'kea-forms'
import { Spinner } from '../Spinner/Spinner'
import { TitleWithIcon } from 'lib/components/TitleWithIcon'

export interface SharingModalProps {
    dashboardId?: number
    insightShortId?: InsightShortId
    insight?: Partial<InsightModel>
    visible: boolean
    closeModal: () => void
}

export function Sharing({ dashboardId, insightShortId, insight, closeModal }: SharingModalProps): JSX.Element {
    const logicProps = {
        dashboardId,
        insightShortId,
    }
    const {
        whitelabelAvailable,
        sharingConfiguration,
        sharingConfigurationLoading,
        showPreview,
        embedCode,
        iframeProperties,
        shareLink,
    } = useValues(sharingLogic(logicProps))
    const { setIsEnabled, togglePreview } = useActions(sharingLogic(logicProps))

    const [iframeLoaded, setIframeLoaded] = useState(false)

    const showNoLegendCheckbox = insight?.filters?.insight === InsightType.TRENDS
    const resource = dashboardId ? 'dashboard' : 'insight'

    useEffect(() => {
        setIframeLoaded(false)
    }, [iframeProperties.src, sharingConfiguration?.enabled, showPreview])

    return (
        <div className="space-y-05">
            {dashboardId ? <DashboardCollaboration dashboardId={dashboardId} /> : undefined}

            {!sharingConfiguration && sharingConfigurationLoading ? (
                <Skeleton />
            ) : !sharingConfiguration ? (
                <p>Something went wrong...</p>
            ) : (
                <>
                    <LemonSwitch
                        id="sharing-switch"
                        label={`Share ${resource} publicly`}
                        checked={sharingConfiguration.enabled}
                        loading={sharingConfigurationLoading}
                        data-attr="sharing-switch"
                        onChange={(active) => {
                            setIsEnabled(active)
                        }}
                        icon={<IconGlobeLock />}
                        fullWidth
                        type="primary"
                    />
                    {sharingConfiguration.enabled && sharingConfiguration.access_token ? (
                        <>
                            <LemonDivider />
                            <div className="space-between-items">
                                <TitleWithIcon
                                    icon={
                                        <Tooltip
                                            title={`Use this HTML snippet to embed the ${resource} on your website`}
                                        >
                                            <IconInfo />
                                        </Tooltip>
                                    }
                                >
                                    <>Embed {resource}</>
                                </TitleWithIcon>
                                <LemonButton
                                    data-attr="sharing-link-button"
                                    size={'small'}
                                    onClick={() => copyToClipboard(shareLink, 'link')}
                                    icon={<IconLink />}
                                >
                                    Copy share link
                                </LemonButton>
                            </div>
                            <CodeSnippet language={Language.HTML}>{embedCode}</CodeSnippet>

                            {insight && (
                                <div className="border-all">
                                    <LemonButton
                                        fullWidth
                                        type="stealth"
                                        sideIcon={showPreview ? <IconUnfoldLess /> : <IconUnfoldMore />}
                                        onClick={togglePreview}
                                    >
                                        Preview
                                        {showPreview && !iframeLoaded ? <Spinner size="sm" className="ml-05" /> : null}
                                    </LemonButton>
                                    {showPreview && (
                                        <div className="SharingPreview border-top">
                                            <iframe
                                                style={{ display: 'block' }}
                                                {...iframeProperties}
                                                onLoad={() => setIframeLoaded(true)}
                                            />
                                        </div>
                                    )}
                                </div>
                            )}

                            <Form logic={sharingLogic} props={logicProps} formKey="embedConfig" className="space-y-05">
                                <Field name="whitelabel" noStyle>
                                    {({ value, onChange }) => (
                                        <LemonSwitch
                                            fullWidth
                                            type="primary"
                                            label={
                                                <>
                                                    <span className="mr-05">Show PostHog branding</span>
                                                    {!whitelabelAvailable ? (
                                                        <Tooltip title="Upgrade to PostHog Scale to hide PostHog branding">
                                                            <IconLock />
                                                        </Tooltip>
                                                    ) : null}
                                                </>
                                            }
                                            onChange={() => onChange(!value)}
                                            checked={!value}
                                            disabled={!whitelabelAvailable}
                                        />
                                    )}
                                </Field>
                                {showNoLegendCheckbox && (
                                    <Field name="noLegend" noStyle>
                                        {({ value, onChange }) => (
                                            <LemonSwitch
                                                fullWidth
                                                type="primary"
                                                label={<div>Show Legend</div>}
                                                onChange={() => onChange(!value)}
                                                checked={!value}
                                            />
                                        )}
                                    </Field>
                                )}
                            </Form>
                        </>
                    ) : null}
                </>
            )}
            <LemonDivider />
            <div className="page-buttons">
                <LemonButton type="secondary" onClick={closeModal}>
                    Done
                </LemonButton>
            </div>
        </div>
    )
}

export function SharingModal(props: SharingModalProps): JSX.Element {
    const { visible, closeModal } = props

    return (
        <>
            <LemonModal
                onCancel={closeModal}
                afterClose={closeModal}
                visible={visible}
                width={440}
                title={`${props.dashboardId ? 'Dashboard' : 'Insight'} permissions`}
            >
                <Sharing {...props} />
            </LemonModal>
        </>
    )
}
