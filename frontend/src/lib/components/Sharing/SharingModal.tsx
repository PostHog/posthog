import './SharingModal.scss'

import { IconCollapse, IconExpand, IconInfo, IconLock } from '@posthog/icons'
import { LemonButton, LemonDivider, LemonModal, LemonSkeleton, LemonSwitch } from '@posthog/lemon-ui'
import { captureException } from '@sentry/react'
import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { TitleWithIcon } from 'lib/components/TitleWithIcon'
import { IconLink } from 'lib/lemon-ui/icons'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { Spinner } from 'lib/lemon-ui/Spinner/Spinner'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { useEffect, useState } from 'react'
import { DashboardCollaboration } from 'scenes/dashboard/DashboardCollaborators'
import { sceneLogic } from 'scenes/sceneLogic'

import { AvailableFeature, InsightModel, InsightShortId, InsightType } from '~/types'

import { sharingLogic } from './sharingLogic'

export const SHARING_MODAL_WIDTH = 600

export interface SharingModalBaseProps {
    dashboardId?: number
    insightShortId?: InsightShortId
    insight?: Partial<InsightModel>
    recordingId?: string

    title?: string
    previewIframe?: boolean
    additionalParams?: Record<string, any>
}

export interface SharingModalProps extends SharingModalBaseProps {
    isOpen: boolean
    closeModal: () => void
    inline?: boolean
}

export function SharingModalContent({
    dashboardId,
    insightShortId,
    insight,
    recordingId,
    additionalParams,
    previewIframe = false,
}: SharingModalBaseProps): JSX.Element {
    const logicProps = {
        dashboardId,
        insightShortId,
        recordingId,
        additionalParams,
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
    const { guardAvailableFeature } = useActions(sceneLogic)

    const [iframeLoaded, setIframeLoaded] = useState(false)

    const showLegendCheckbox = insight?.filters?.insight === InsightType.TRENDS
    const resource = dashboardId ? 'dashboard' : insightShortId ? 'insight' : recordingId ? 'recording' : 'this'

    useEffect(() => {
        setIframeLoaded(false)
    }, [iframeProperties.src, sharingConfiguration?.enabled, showPreview])

    return (
        <div className="space-y-4">
            {dashboardId ? (
                <>
                    <DashboardCollaboration dashboardId={dashboardId} />
                    <LemonDivider />
                </>
            ) : undefined}

            <div className="space-y-2">
                {!sharingConfiguration && sharingConfigurationLoading ? (
                    <LemonSkeleton.Row repeat={3} />
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
                            bordered
                            fullWidth
                        />

                        {sharingConfiguration.enabled && sharingConfiguration.access_token ? (
                            <>
                                <div className="space-y-2">
                                    <LemonButton
                                        data-attr="sharing-link-button"
                                        type="secondary"
                                        onClick={() => {
                                            // TRICKY: there's a chance this was sending useless errors to Sentry
                                            // even when it succeeded, so we're explicitly ignoring the promise success
                                            // and naming the error when reported to Sentry - @pauldambra
                                            copyToClipboard(shareLink, 'link').catch((e) =>
                                                captureException(
                                                    new Error('unexpected sharing modal clipboard error: ' + e.message)
                                                )
                                            )
                                        }}
                                        icon={<IconLink />}
                                        fullWidth
                                        className="mb-4"
                                    >
                                        Copy public link
                                    </LemonButton>
                                    <TitleWithIcon
                                        icon={
                                            <Tooltip
                                                title={`Use the HTML snippet below to embed the ${resource} on your website`}
                                            >
                                                <IconInfo />
                                            </Tooltip>
                                        }
                                    >
                                        <b>Embed {resource}</b>
                                    </TitleWithIcon>
                                    <CodeSnippet language={Language.HTML}>{embedCode}</CodeSnippet>
                                </div>
                                <Form
                                    logic={sharingLogic}
                                    props={logicProps}
                                    formKey="embedConfig"
                                    className="space-y-2"
                                >
                                    <LemonField name="whitelabel">
                                        {({ value, onChange }) => (
                                            <LemonSwitch
                                                fullWidth
                                                bordered
                                                label={
                                                    <div className="flex items-center">
                                                        <span>Show PostHog branding</span>
                                                        {!whitelabelAvailable && (
                                                            <Tooltip title="This is a premium feature, click to learn more.">
                                                                <IconLock className="ml-1 text-muted text-base" />
                                                            </Tooltip>
                                                        )}
                                                    </div>
                                                }
                                                onChange={() =>
                                                    guardAvailableFeature(AvailableFeature.WHITE_LABELLING, () =>
                                                        onChange(!value)
                                                    )
                                                }
                                                checked={!value}
                                            />
                                        )}
                                    </LemonField>
                                    {insight && (
                                        <LemonField name="noHeader">
                                            {({ value, onChange }) => (
                                                <LemonSwitch
                                                    fullWidth
                                                    bordered
                                                    label={<div>Show title and description</div>}
                                                    onChange={() => onChange(!value)}
                                                    checked={!value}
                                                />
                                            )}
                                        </LemonField>
                                    )}
                                    {showLegendCheckbox && (
                                        <LemonField name="legend">
                                            {({ value, onChange }) => (
                                                <LemonSwitch
                                                    fullWidth
                                                    bordered
                                                    label={<div>Show legend</div>}
                                                    onChange={() => onChange(!value)}
                                                    checked={value}
                                                />
                                            )}
                                        </LemonField>
                                    )}
                                    {recordingId && (
                                        <LemonField name="showInspector">
                                            {({ value, onChange }) => (
                                                <LemonSwitch
                                                    fullWidth
                                                    bordered
                                                    label={<div>Show inspector panel</div>}
                                                    onChange={onChange}
                                                    checked={value}
                                                />
                                            )}
                                        </LemonField>
                                    )}

                                    {previewIframe && (
                                        <div className="rounded border">
                                            <LemonButton
                                                fullWidth
                                                sideIcon={showPreview ? <IconCollapse /> : <IconExpand />}
                                                onClick={togglePreview}
                                            >
                                                Preview
                                                {showPreview && !iframeLoaded ? <Spinner className="ml-2" /> : null}
                                            </LemonButton>
                                            {showPreview && (
                                                <div className="SharingPreview border-t">
                                                    <iframe
                                                        className="block"
                                                        {...iframeProperties}
                                                        onLoad={() => setIframeLoaded(true)}
                                                    />
                                                </div>
                                            )}
                                        </div>
                                    )}
                                </Form>
                            </>
                        ) : null}
                    </>
                )}
            </div>
        </div>
    )
}

export function SharingModal({ closeModal, isOpen, inline, title, ...props }: SharingModalProps): JSX.Element {
    return (
        <LemonModal
            onClose={closeModal}
            isOpen={isOpen}
            width={SHARING_MODAL_WIDTH}
            title={title ?? 'Sharing'}
            footer={
                <LemonButton type="secondary" onClick={closeModal}>
                    Done
                </LemonButton>
            }
            inline={inline}
        >
            <SharingModalContent {...props} />
        </LemonModal>
    )
}

SharingModal.open = (props: SharingModalBaseProps) => {
    LemonDialog.open({
        title: props.title ?? 'Sharing',
        content: (
            <>
                <SharingModalContent {...props} />
            </>
        ),
        width: SHARING_MODAL_WIDTH,
        primaryButton: {
            children: 'Close',
            type: 'secondary',
        },
    })
}
