import React, { useEffect, useState } from 'react'
import { LemonModal } from 'lib/components/LemonModal'
import { InsightModel, InsightShortId, InsightType } from '~/types'
import { useActions, useValues } from 'kea'
import { sharingLogic } from './sharingLogic'
import { Skeleton } from 'antd'
import { LemonButton, LemonDivider, LemonSwitch } from '@posthog/lemon-ui'
import { copyToClipboard } from 'lib/utils'
import { IconGlobeLock, IconInfo, IconLink, IconLockLemon, IconUnfoldLess, IconUnfoldMore } from '../icons'
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

    const showLegendCheckbox = insight?.filters?.insight === InsightType.TRENDS
    const resource = dashboardId ? 'dashboard' : 'insight'

    useEffect(() => {
        setIframeLoaded(false)
    }, [iframeProperties.src, sharingConfiguration?.enabled, showPreview])

    return (
        <div className="space-y-4">
            <h3>{dashboardId ? 'Dashboard' : 'Insight'} permissions</h3>
            <LemonDivider large />

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
                            <LemonDivider large />
                            <div className="space-y-2">
                                <div className="flex justify-between">
                                    <TitleWithIcon
                                        icon={
                                            <Tooltip
                                                title={`Use this HTML snippet to embed the ${resource} on your website`}
                                            >
                                                <IconInfo />
                                            </Tooltip>
                                        }
                                    >
                                        <strong>Embed {resource}</strong>
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
                            </div>

                            <Form logic={sharingLogic} props={logicProps} formKey="embedConfig" className="space-y-2">
                                {insight && (
                                    <div className="rounded border-all">
                                        <LemonButton
                                            fullWidth
                                            type="stealth"
                                            sideIcon={showPreview ? <IconUnfoldLess /> : <IconUnfoldMore />}
                                            onClick={togglePreview}
                                        >
                                            Preview
                                            {showPreview && !iframeLoaded ? (
                                                <Spinner size="sm" className="ml-2" />
                                            ) : null}
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
                                <Field name="whitelabel" noStyle>
                                    {({ value, onChange }) => (
                                        <LemonSwitch
                                            fullWidth
                                            type="primary"
                                            label={
                                                <div className="flex">
                                                    <div className="mr-2" style={{ lineHeight: '1.5rem' }}>
                                                        Show PostHog branding
                                                    </div>
                                                    {!whitelabelAvailable ? (
                                                        <Tooltip title="Upgrade to PostHog Scale to hide PostHog branding">
                                                            <IconLockLemon />
                                                        </Tooltip>
                                                    ) : null}
                                                </div>
                                            }
                                            onChange={() => onChange(!value)}
                                            checked={!value}
                                            disabled={!whitelabelAvailable}
                                        />
                                    )}
                                </Field>
                                {insight && (
                                    <Field name="noHeader" noStyle>
                                        {({ value, onChange }) => (
                                            <LemonSwitch
                                                fullWidth
                                                type="primary"
                                                label={<div>Show title and description</div>}
                                                onChange={() => onChange(!value)}
                                                checked={!value}
                                            />
                                        )}
                                    </Field>
                                )}
                                {showLegendCheckbox && (
                                    <Field name="legend" noStyle>
                                        {({ value, onChange }) => (
                                            <LemonSwitch
                                                fullWidth
                                                type="primary"
                                                label={<div>Show legend</div>}
                                                onChange={() => onChange(!value)}
                                                checked={value}
                                            />
                                        )}
                                    </Field>
                                )}
                            </Form>
                        </>
                    ) : null}
                </>
            )}
            <LemonDivider large />
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
            <LemonModal onCancel={closeModal} afterClose={closeModal} visible={visible} width={480}>
                <Sharing {...props} />
            </LemonModal>
        </>
    )
}
