import { useEffect, useState } from 'react'
import { InsightModel, InsightShortId, InsightType } from '~/types'
import { useActions, useValues } from 'kea'
import { sharingLogic } from './sharingLogic'
import { LemonButton, LemonDivider, LemonSwitch } from '@posthog/lemon-ui'
import { copyToClipboard } from 'lib/utils'
import { IconGlobeLock, IconInfo, IconLink, IconLock, IconUnfoldLess, IconUnfoldMore } from '../icons'
import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { DashboardCollaboration } from 'scenes/dashboard/DashboardCollaborators'
import { Field } from 'lib/forms/Field'
import { Tooltip } from 'lib/components/Tooltip'
import './SharingModal.scss'
import { Form } from 'kea-forms'
import { Spinner } from '../Spinner/Spinner'
import { TitleWithIcon } from 'lib/components/TitleWithIcon'
import { LemonModal } from '../LemonModal'
import { LemonSkeleton } from '../LemonSkeleton'

export interface SharingModalProps {
    dashboardId?: number
    insightShortId?: InsightShortId
    insight?: Partial<InsightModel>
    isOpen: boolean
    closeModal: () => void
    inline?: boolean
}

export function SharingModal({
    dashboardId,
    insightShortId,
    insight,
    closeModal,
    isOpen,
    inline,
}: SharingModalProps): JSX.Element {
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
        <LemonModal
            onClose={closeModal}
            isOpen={isOpen}
            width={480}
            title={`${dashboardId ? 'Dashboard' : 'Insight'} permissions`}
            footer={
                <LemonButton type="secondary" onClick={closeModal}>
                    Done
                </LemonButton>
            }
            inline={inline}
        >
            <div className="space-y-4">
                {dashboardId ? <DashboardCollaboration dashboardId={dashboardId} /> : undefined}

                {!sharingConfiguration && sharingConfigurationLoading ? (
                    <div className="space-y-4">
                        <LemonSkeleton.Row repeat={3} />
                    </div>
                ) : !sharingConfiguration ? (
                    <p>Something went wrong...</p>
                ) : (
                    <>
                        <LemonSwitch
                            id="sharing-switch"
                            label={`Share ${resource} publicly`}
                            checked={sharingConfiguration.enabled}
                            data-attr="sharing-switch"
                            onChange={(active) => setIsEnabled(active)}
                            icon={<IconGlobeLock />}
                            bordered
                            fullWidth
                        />

                        {sharingConfiguration.enabled && sharingConfiguration.access_token ? (
                            <>
                                <LemonDivider className="my-4" />
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

                                <Form
                                    logic={sharingLogic}
                                    props={logicProps}
                                    formKey="embedConfig"
                                    className="space-y-2"
                                >
                                    {insight && (
                                        <div className="rounded border">
                                            <LemonButton
                                                fullWidth
                                                status="stealth"
                                                sideIcon={showPreview ? <IconUnfoldLess /> : <IconUnfoldMore />}
                                                onClick={togglePreview}
                                            >
                                                Preview
                                                {showPreview && !iframeLoaded ? <Spinner className="ml-2" /> : null}
                                            </LemonButton>
                                            {showPreview && (
                                                <div className="SharingPreview border-t">
                                                    <iframe
                                                        style={{ display: 'block' }}
                                                        {...iframeProperties}
                                                        onLoad={() => setIframeLoaded(true)}
                                                    />
                                                </div>
                                            )}
                                        </div>
                                    )}
                                    <Field name="whitelabel">
                                        {({ value, onChange }) => (
                                            <LemonSwitch
                                                fullWidth
                                                bordered
                                                label={
                                                    <div className="flex">
                                                        <div className="mr-2" style={{ lineHeight: '1.5rem' }}>
                                                            Show PostHog branding
                                                        </div>
                                                        {!whitelabelAvailable ? (
                                                            <Tooltip title="Upgrade to PostHog Scale to hide PostHog branding">
                                                                <IconLock />
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
                                        <Field name="noHeader">
                                            {({ value, onChange }) => (
                                                <LemonSwitch
                                                    fullWidth
                                                    bordered
                                                    label={<div>Show title and description</div>}
                                                    onChange={() => onChange(!value)}
                                                    checked={!value}
                                                />
                                            )}
                                        </Field>
                                    )}
                                    {showLegendCheckbox && (
                                        <Field name="legend">
                                            {({ value, onChange }) => (
                                                <LemonSwitch
                                                    fullWidth
                                                    bordered
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
            </div>
        </LemonModal>
    )
}
