import './SharingModal.scss'

import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { router } from 'kea-router'
import posthog from 'posthog-js'
import { ReactNode, useEffect, useState } from 'react'

import { IconCollapse, IconExpand, IconInfo, IconLock } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonDivider, LemonModal, LemonSkeleton, LemonSwitch } from '@posthog/lemon-ui'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { TemplateLinkSection } from 'lib/components/Sharing/TemplateLinkSection'
import {
    TEMPLATE_LINK_HEADING,
    TEMPLATE_LINK_PII_WARNING,
    TEMPLATE_LINK_TOOLTIP,
} from 'lib/components/Sharing/templateLinkMessages'
import { TitleWithIcon } from 'lib/components/TitleWithIcon'
import { FEATURE_FLAGS } from 'lib/constants'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { Spinner } from 'lib/lemon-ui/Spinner/Spinner'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { IconLink } from 'lib/lemon-ui/icons'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { getInsightDefinitionUrl } from 'lib/utils/insightLinks'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'
import { urls } from 'scenes/urls'

import { AccessControlPopoutCTA } from '~/layout/navigation-3000/sidepanel/panels/access_control/AccessControlPopoutCTA'
import { isInsightVizNode } from '~/queries/utils'
import {
    AccessControlLevel,
    AccessControlResourceType,
    AvailableFeature,
    InsightShortId,
    QueryBasedInsightModel,
} from '~/types'

import { AccessControlAction, accessLevelSatisfied } from '../AccessControlAction'
import { upgradeModalLogic } from '../UpgradeModal/upgradeModalLogic'
import { SharePasswordsTable } from './SharePasswordsTable'
import { sharingLogic } from './sharingLogic'

function getResourceType(
    dashboardId?: number,
    insightShortId?: InsightShortId,
    recordingId?: string
): AccessControlResourceType {
    if (dashboardId) {
        return AccessControlResourceType.Dashboard
    }
    if (insightShortId) {
        return AccessControlResourceType.Insight
    }
    if (recordingId) {
        return AccessControlResourceType.SessionRecording
    }
    return AccessControlResourceType.Project
}

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
    userAccessLevel?: AccessControlLevel
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
    userAccessLevel,
}: SharingModalBaseProps): JSX.Element {
    const logicProps = {
        dashboardId,
        insightShortId,
        recordingId,
        additionalParams,
    }
    const {
        whitelabelAvailable,
        advancedPermissionsAvailable,
        sharingConfiguration,
        sharingConfigurationLoading,
        showPreview,
        embedCode,
        iframeProperties,
        shareLink,
        sharingAllowed,
    } = useValues(sharingLogic(logicProps))
    const { setIsEnabled, setPasswordRequired, togglePreview, setSharingSettingsValue } = useActions(
        sharingLogic(logicProps)
    )
    const { guardAvailableFeature } = useValues(upgradeModalLogic)
    const { preflight } = useValues(preflightLogic)
    const siteUrl = preflight?.site_url || window.location.origin
    const { featureFlags } = useValues(featureFlagLogic)
    const passwordProtectedSharesEnabled = !!featureFlags[FEATURE_FLAGS.PASSWORD_PROTECTED_SHARES]

    const { push } = useActions(router)

    const [iframeLoaded, setIframeLoaded] = useState(false)

    const resource = dashboardId ? 'dashboard' : insightShortId ? 'insight' : recordingId ? 'recording' : 'this'
    const hasEditAccess = userAccessLevel
        ? accessLevelSatisfied(resource as AccessControlResourceType, userAccessLevel, AccessControlLevel.Editor)
        : true

    useEffect(() => {
        setIframeLoaded(false)
    }, [iframeProperties.src, iframeProperties.key, sharingConfiguration?.enabled, showPreview])

    return (
        <div className="deprecated-space-y-4">
            {dashboardId ? (
                <>
                    <AccessControlPopoutCTA
                        resourceType={AccessControlResourceType.Dashboard}
                        callback={() => {
                            push(urls.dashboard(dashboardId))
                        }}
                    />
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
                        {!sharingAllowed ? (
                            <LemonBanner type="warning">Public sharing is disabled for this organization.</LemonBanner>
                        ) : (
                            <AccessControlAction
                                resourceType={getResourceType(dashboardId, insightShortId, recordingId)}
                                minAccessLevel={AccessControlLevel.Editor}
                                userAccessLevel={userAccessLevel}
                            >
                                <LemonSwitch
                                    id="sharing-switch"
                                    label={`Share ${resource} publicly`}
                                    checked={sharingConfiguration.enabled}
                                    data-attr="sharing-switch"
                                    onChange={(active) => setIsEnabled(active)}
                                    bordered
                                    fullWidth
                                    loading={sharingConfigurationLoading}
                                />
                            </AccessControlAction>
                        )}

                        {sharingAllowed && sharingConfiguration.enabled && sharingConfiguration.access_token ? (
                            <>
                                <div className="deprecated-space-y-2">
                                    {passwordProtectedSharesEnabled && (
                                        <div className="LemonSwitch LemonSwitch--medium LemonSwitch--bordered LemonSwitch--full-width flex-col py-1.5">
                                            <LemonSwitch
                                                className="px-0"
                                                fullWidth
                                                label={
                                                    <div className="flex items-center">
                                                        Password protect
                                                        {!advancedPermissionsAvailable && (
                                                            <Tooltip title="This is a premium feature, click to learn more.">
                                                                <IconLock className="ml-1.5 text-muted text-lg" />
                                                            </Tooltip>
                                                        )}
                                                    </div>
                                                }
                                                onChange={(passwordRequired: boolean) =>
                                                    guardAvailableFeature(AvailableFeature.ADVANCED_PERMISSIONS, () =>
                                                        setPasswordRequired(passwordRequired)
                                                    )
                                                }
                                                checked={sharingConfiguration.password_required}
                                            />
                                            {sharingConfiguration.password_required && (
                                                <div className="mt-1 w-full">
                                                    <SharePasswordsTable
                                                        dashboardId={dashboardId}
                                                        insightId={insight?.id}
                                                        recordingId={recordingId}
                                                    />
                                                </div>
                                            )}
                                        </div>
                                    )}
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
                                {hasEditAccess && (
                                    <Form
                                        logic={sharingLogic}
                                        props={logicProps}
                                        formKey="sharingSettings"
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
                                                            guardAvailableFeature(
                                                                AvailableFeature.WHITE_LABELLING,
                                                                () => {
                                                                    // setSharingSettingsValue is used to update the form state and report the event
                                                                    setSharingSettingsValue('whitelabel', !value)
                                                                }
                                                            )
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

                                            {dashboardId && (
                                                <LemonField name="hideExtraDetails">
                                                    {({ value, onChange }) => (
                                                        <LemonSwitch
                                                            fullWidth
                                                            bordered
                                                            label={
                                                                <div className="flex items-center">
                                                                    <span>Show insight details</span>
                                                                    <Tooltip title="When disabled, viewers won't see the extra insights details like the who created the insight and the applied filters.">
                                                                        <IconInfo className="ml-1.5 text-secondary text-lg" />
                                                                    </Tooltip>
                                                                </div>
                                                            }
                                                            onChange={() => onChange(!value)}
                                                            checked={!value}
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
                                )}
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
