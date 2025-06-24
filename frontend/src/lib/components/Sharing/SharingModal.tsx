import './SharingModal.scss'

import { IconCollapse, IconExpand, IconInfo, IconLock } from '@posthog/icons'
import { LemonButton, LemonDivider, LemonModal, LemonSkeleton, LemonSwitch } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { router } from 'kea-router'
import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import {
    TEMPLATE_LINK_HEADING,
    TEMPLATE_LINK_PII_WARNING,
    TEMPLATE_LINK_TOOLTIP,
} from 'lib/components/Sharing/templateLinkMessages'
import { TemplateLinkSection } from 'lib/components/Sharing/TemplateLinkSection'
import { TitleWithIcon } from 'lib/components/TitleWithIcon'
import { IconLink } from 'lib/lemon-ui/icons'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { Spinner } from 'lib/lemon-ui/Spinner/Spinner'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { getInsightDefinitionUrl } from 'lib/utils/insightLinks'
import posthog from 'posthog-js'
import { ReactNode, useEffect, useState } from 'react'
import { DashboardCollaboration } from 'scenes/dashboard/DashboardCollaborators'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { urls } from 'scenes/urls'

import { AccessControlPopoutCTA } from '~/layout/navigation-3000/sidepanel/panels/access_control/AccessControlPopoutCTA'
import { isInsightVizNode } from '~/queries/utils'
import { AccessControlResourceType, AvailableFeature, InsightShortId, QueryBasedInsightModel } from '~/types'

import { upgradeModalLogic } from '../UpgradeModal/upgradeModalLogic'
import { sharingLogic } from './sharingLogic'

export const SHARING_MODAL_WIDTH = 600

export interface SharingModalBaseProps {
    dashboardId?: number
    insightShortId?: InsightShortId
    insight?: Partial<QueryBasedInsightModel>
    recordingId?: string

    title?: string
    previewIframe?: boolean
    additionalParams?: Record<string, any>
    /**
     * When generating a link to a recording, this form can be used to allow the user to specify a timestamp
     */
    recordingLinkTimeForm?: ReactNode
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
    recordingLinkTimeForm = undefined,
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
    const { setIsEnabled, togglePreview, setEmbedConfigValue } = useActions(sharingLogic(logicProps))
    const { guardAvailableFeature } = useValues(upgradeModalLogic)
    const { preflight } = useValues(preflightLogic)
    const siteUrl = preflight?.site_url || window.location.origin

    const { push } = useActions(router)

    const [iframeLoaded, setIframeLoaded] = useState(false)

    const resource = dashboardId ? 'dashboard' : insightShortId ? 'insight' : recordingId ? 'recording' : 'this'

    useEffect(() => {
        setIframeLoaded(false)
    }, [iframeProperties.src, sharingConfiguration?.enabled, showPreview])

    return (
        <div className="deprecated-space-y-4">
            {dashboardId ? (
                <>
                    <DashboardCollaboration dashboardId={dashboardId} />
                    <LemonDivider />
                </>
            ) : undefined}

            {insightShortId ? (
                <>
                    <AccessControlPopoutCTA
                        resourceType={AccessControlResourceType.Insight}
                        callback={() => {
                            push(urls.insightView(insightShortId))
                        }}
                    />
                    <LemonDivider />
                </>
            ) : undefined}

            <div className="deprecated-space-y-2">
                {!sharingConfiguration && sharingConfigurationLoading ? (
                    <LemonSkeleton.Row repeat={3} />
                ) : !sharingConfiguration ? (
                    <p>Something went wrong...</p>
                ) : (
                    <>
                        <h3>Sharing</h3>
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
                                <div className="deprecated-space-y-2">
                                    <LemonButton
                                        data-attr="sharing-link-button"
                                        type="secondary"
                                        onClick={() => {
                                            // TRICKY: there's a chance this was sending useless errors to error tracking
                                            // even when it succeeded, so we're explicitly ignoring the promise success
                                            // and naming the error when reported to error tracking - @pauldambra
                                            copyToClipboard(shareLink, shareLink).catch((e) =>
                                                posthog.captureException(
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
                                    {recordingLinkTimeForm}
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
                                    className="deprecated-space-y-2"
                                >
                                    <div className="grid grid-cols-2 gap-2 grid-flow *:odd:last:col-span-2">
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
                                        <LemonField name="whitelabel">
                                            {({ value }) => (
                                                <LemonSwitch
                                                    fullWidth
                                                    bordered
                                                    label={
                                                        <div className="flex items-center">
                                                            <span>Show PostHog branding</span>
                                                            {!whitelabelAvailable && (
                                                                <Tooltip title="This is a premium feature, click to learn more.">
                                                                    <IconLock className="ml-1.5 text-secondary text-lg" />
                                                                </Tooltip>
                                                            )}
                                                        </div>
                                                    }
                                                    onChange={() =>
                                                        guardAvailableFeature(AvailableFeature.WHITE_LABELLING, () => {
                                                            // setEmbedConfigValue is used to update the form state and report the event
                                                            setEmbedConfigValue('whitelabel', !value)
                                                        })
                                                    }
                                                    checked={!value}
                                                />
                                            )}
                                        </LemonField>

                                        {isInsightVizNode(insight?.query) && insightShortId && (
                                            // These options are only valid for `InsightVizNode`s, and they rely on `insightVizDataLogic`
                                            <>
                                                <LegendCheckbox insightShortId={insightShortId} />
                                                <DetailedResultsCheckbox insightShortId={insightShortId} />
                                            </>
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
                                    </div>

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
            {insight?.query && (
                <>
                    <LemonDivider />
                    <TemplateLinkSection
                        templateLink={getInsightDefinitionUrl({ query: insight.query }, siteUrl)}
                        heading={TEMPLATE_LINK_HEADING}
                        tooltip={TEMPLATE_LINK_TOOLTIP}
                        piiWarning={TEMPLATE_LINK_PII_WARNING}
                    />
                </>
            )}
        </div>
    )
}

function DetailedResultsCheckbox({ insightShortId }: { insightShortId: InsightShortId }): JSX.Element | null {
    const { hasDetailedResultsTable } = useValues(insightVizDataLogic({ dashboardItemId: insightShortId }))

    if (!hasDetailedResultsTable) {
        return null // No detailed results toggle
    }

    return (
        <LemonField name="detailed">
            {({ value, onChange }) => (
                <LemonSwitch
                    fullWidth
                    bordered
                    label="Show detailed results"
                    onChange={() => onChange(!value)}
                    checked={value}
                />
            )}
        </LemonField>
    )
}

function LegendCheckbox({ insightShortId }: { insightShortId: InsightShortId }): JSX.Element | null {
    const { hasLegend } = useValues(insightVizDataLogic({ dashboardItemId: insightShortId }))

    if (!hasLegend) {
        return null // No legend to toggle
    }

    return (
        <LemonField name="legend">
            {({ value, onChange }) => (
                <LemonSwitch fullWidth bordered label="Show legend" onChange={() => onChange(!value)} checked={value} />
            )}
        </LemonField>
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
