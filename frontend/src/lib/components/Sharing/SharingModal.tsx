import './SharingModal.scss'

import { LemonButton, LemonSwitch } from '@posthog/lemon-ui'
import { captureException } from '@sentry/react'
import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { TitleWithIcon } from 'lib/components/TitleWithIcon'
import { Field } from 'lib/forms/Field'
import { IconGlobeLock, IconInfo, IconLink, IconLock, IconUnfoldLess, IconUnfoldMore } from 'lib/lemon-ui/icons'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { Spinner } from 'lib/lemon-ui/Spinner/Spinner'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { useEffect, useState } from 'react'
import { DashboardCollaboration } from 'scenes/dashboard/DashboardCollaborators'

import { InsightModel, InsightShortId, InsightType } from '~/types'

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

    const [iframeLoaded, setIframeLoaded] = useState(false)

    const showLegendCheckbox = insight?.filters?.insight === InsightType.TRENDS
    const resource = dashboardId ? 'dashboard' : insightShortId ? 'insight' : recordingId ? 'recording' : 'this'

    useEffect(() => {
        setIframeLoaded(false)
    }, [iframeProperties.src, sharingConfiguration?.enabled, showPreview])

    return (
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
                            <div className="space-y-2">
                                <div className="flex justify-between">
                                    <TitleWithIcon
                                        icon={
                                            <Tooltip
                                                title={`Use this HTML snippet to embed the ${resource} on your website`}
                                            >
                                                <span>
                                                    <IconInfo />
                                                </span>
                                            </Tooltip>
                                        }
                                    >
                                        <strong>Embed {resource}</strong>
                                    </TitleWithIcon>
                                    <LemonButton
                                        data-attr="sharing-link-button"
                                        size="small"
                                        onClick={() => {
                                            // TRICKY: there's a chance this was sending useless errors to Sentry
                                            // even when it succeeded, so we're explicitly ignoring the promise success
                                            // and naming the error when reported to Sentry
                                            copyToClipboard(shareLink, 'link')
                                                .then(() => {}) // purposefully no-op
                                                .catch((e) =>
                                                    captureException(
                                                        new Error(
                                                            'unexpected sharing modal clipboard error: ' + e.message
                                                        )
                                                    )
                                                )
                                        }}
                                        icon={<IconLink />}
                                    >
                                        Copy public link
                                    </LemonButton>
                                </div>
                                <CodeSnippet language={Language.HTML}>{embedCode}</CodeSnippet>
                            </div>

                            <Form logic={sharingLogic} props={logicProps} formKey="embedConfig" className="space-y-2">
                                <Field name="whitelabel">
                                    {({ value, onChange }) => (
                                        <LemonSwitch
                                            fullWidth
                                            bordered
                                            label={
                                                <div className="flex items-center">
                                                    <span>Show PostHog branding</span>
                                                    {!whitelabelAvailable ? (
                                                        <Tooltip title="Upgrade to any paid plan to hide PostHog branding">
                                                            <span>
                                                                <IconLock className="ml-2" />
                                                            </span>
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
                                {recordingId && (
                                    <Field name="showInspector">
                                        {({ value, onChange }) => (
                                            <LemonSwitch
                                                fullWidth
                                                bordered
                                                label={<div>Show inspector panel</div>}
                                                onChange={onChange}
                                                checked={value}
                                            />
                                        )}
                                    </Field>
                                )}

                                {previewIframe && (
                                    <div className="rounded border">
                                        <LemonButton
                                            fullWidth
                                            sideIcon={showPreview ? <IconUnfoldLess /> : <IconUnfoldMore />}
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
