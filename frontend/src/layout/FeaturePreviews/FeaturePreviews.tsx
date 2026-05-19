import { useActions, useAsyncActions, useValues } from 'kea'
import { useLayoutEffect, useState } from 'react'

import { IconBell, IconCheck } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonInput, LemonSwitch, LemonTextArea, Link } from '@posthog/lemon-ui'

import { BasicCard } from 'lib/components/Cards/BasicCard'
import { FEATURE_FLAGS } from 'lib/constants'
import { IconLink } from 'lib/lemon-ui/icons'
import { SpinnerOverlay } from 'lib/lemon-ui/Spinner'
import { Label } from 'lib/ui/Label/Label'
import { userLogic } from 'scenes/userLogic'

import { AvailableFeature } from '~/types'

import { EnrichedEarlyAccessFeature, featurePreviewsLogic } from './featurePreviewsLogic'

type AvailableFeatureChecker = (feature: AvailableFeature) => boolean

interface FeaturePreviewWarning {
    /** Returns the warning to display for a feature, or null if none should show. */
    resolve: (hasAvailableFeature: AvailableFeatureChecker) => React.ReactNode | null
}

/**
 * Per-flag warnings shown on the early-access card. Add an entry here to surface a warning
 * for a specific preview without touching the FeaturePreview component itself.
 */
const FEATURE_PREVIEW_WARNINGS: Record<string, FeaturePreviewWarning> = {
    [FEATURE_FLAGS.FEATURE_FLAG_NOTIFICATIONS]: {
        resolve: (hasAvailableFeature) =>
            hasAvailableFeature(AvailableFeature.AUDIT_LOGS)
                ? null
                : 'This feature requires the Enterprise plan or the Scale add-on. Enabling the preview will not unlock it on your current plan.',
    },
}

const hasPosthogJsFailedToLoadFeaturePreviews = (): boolean => !!window.POSTHOG_GLOBAL_ERRORS?.onFeatureFlagsLoadError

// Feature previews can be linked to by using hash in the url
// example external link: https://app.posthog.com/settings/user-feature-previews#llm-analytics
export function FeaturePreviews(): JSX.Element {
    const { filteredEarlyAccessFeatures, rawEarlyAccessFeaturesLoading, searchTerm } = useValues(featurePreviewsLogic)
    const { hasAvailableFeature } = useValues(userLogic)
    const { loadEarlyAccessFeatures, setSearchTerm } = useActions(featurePreviewsLogic)

    useLayoutEffect(() => loadEarlyAccessFeatures(), [loadEarlyAccessFeatures])

    const betaFeatures = filteredEarlyAccessFeatures.filter((f) => f.stage === 'beta')
    const shouldShowEmptyState =
        filteredEarlyAccessFeatures.length === 0 && !rawEarlyAccessFeaturesLoading && !searchTerm
    const failedToLoadFeaturePreviews = shouldShowEmptyState && hasPosthogJsFailedToLoadFeaturePreviews()

    return (
        <div className="flex flex-col gap-2">
            {failedToLoadFeaturePreviews && (
                <LemonBanner type="warning" className="mb-2">
                    <div className="flex flex-col gap-2">
                        <span>
                            We couldn't load our internal feature flags. This could be due to the presence of adblockers
                            running in your browser or due to a network issue (e.g. slow wifi).
                        </span>
                        <span className="italic">
                            Note: If you use feature flags for your app, you can avoid this issue for your users by
                            using a{' '}
                            <Link to="https://posthog.com/docs/advanced/proxy" target="_blank">
                                reverse proxy
                            </Link>
                            .
                        </span>
                    </div>
                </LemonBanner>
            )}
            {rawEarlyAccessFeaturesLoading ? (
                <SpinnerOverlay />
            ) : (
                <>
                    {!shouldShowEmptyState && (
                        <LemonInput
                            type="search"
                            placeholder="Search feature previews..."
                            value={searchTerm}
                            onChange={setSearchTerm}
                            allowClear
                        />
                    )}
                    {betaFeatures.length === 0 && searchTerm.trim() ? (
                        <p className="text-secondary text-center mt-4">No matching feature previews</p>
                    ) : (
                        betaFeatures.map((feature) => (
                            <div key={feature.flagKey}>
                                <FeaturePreview
                                    feature={feature}
                                    warning={FEATURE_PREVIEW_WARNINGS[feature.flagKey]?.resolve(hasAvailableFeature)}
                                />
                            </div>
                        ))
                    )}
                </>
            )}
        </div>
    )
}

export function FeaturePreviewsComingSoon(): JSX.Element {
    const { filteredEarlyAccessFeatures, rawEarlyAccessFeaturesLoading } = useValues(featurePreviewsLogic)
    const { loadEarlyAccessFeatures } = useActions(featurePreviewsLogic)

    useLayoutEffect(() => loadEarlyAccessFeatures(), [loadEarlyAccessFeatures])

    const conceptFeatures = filteredEarlyAccessFeatures.filter((f) => f.stage === 'concept')

    return (
        <div className="flex flex-col gap-2">
            {rawEarlyAccessFeaturesLoading ? (
                <SpinnerOverlay />
            ) : (
                conceptFeatures.map((feature) => (
                    <div key={feature.flagKey}>
                        <ConceptPreview feature={feature} />
                    </div>
                ))
            )}
        </div>
    )
}

interface PreviewCardProps {
    feature: EnrichedEarlyAccessFeature
    title: React.ReactNode
    description: React.ReactNode
    actions: React.ReactNode
    children?: React.ReactNode
}

function PreviewCard({ feature, title, description, actions, children }: PreviewCardProps): JSX.Element {
    return (
        <BasicCard
            className="pl-4 pr-2 pt-2 pb-3 gap-1 @container"
            id={`${feature.flagKey}`}
            backgroundColor="var(--color-bg-surface-primary)"
        >
            <div className="flex flex-col justify-between gap-2">
                <div className="flex flex-col gap-1">
                    {title}
                    {description}
                </div>
                <div className="flex flex-col gap-2">{actions}</div>
            </div>
            {children}
        </BasicCard>
    )
}

function ConceptPreview({ feature }: { feature: EnrichedEarlyAccessFeature }): JSX.Element {
    const { updateEarlyAccessFeatureEnrollment, copyExternalFeaturePreviewLink } = useActions(featurePreviewsLogic)

    const { flagKey, enabled, name, description } = feature

    return (
        <PreviewCard
            feature={feature}
            title={
                <div className="flex items-center gap-1">
                    <h4 className="font-bold mb-0">{name}</h4>
                    <LemonButton
                        icon={<IconLink />}
                        size="xsmall"
                        onClick={() => copyExternalFeaturePreviewLink(flagKey)}
                    />
                </div>
            }
            description={
                <p className="m-0 max-w-prose">
                    {description || <span className="text-tertiary">No description</span>}
                </p>
            }
            actions={
                <div className="flex flex-col gap-2">
                    <LemonButton
                        type="primary"
                        disabledReason={
                            enabled && "You have already expressed your interest. We'll contact you when it's ready"
                        }
                        onClick={() => updateEarlyAccessFeatureEnrollment(flagKey, true, feature.stage)}
                        size="small"
                        sideIcon={enabled ? <IconCheck /> : <IconBell />}
                        className="w-fit"
                    >
                        {enabled ? 'Registered' : 'Get notified'}
                    </LemonButton>
                </div>
            }
        />
    )
}

interface FeaturePreviewProps {
    feature: EnrichedEarlyAccessFeature
    /** Optional warning rendered under the description (e.g. plan/add-on requirements). */
    warning?: React.ReactNode
}

function FeaturePreview({ feature, warning }: FeaturePreviewProps): JSX.Element {
    const { activeFeedbackFlagKey, activeFeedbackFlagKeyLoading } = useValues(featurePreviewsLogic)
    const {
        beginEarlyAccessFeatureFeedback,
        cancelEarlyAccessFeatureFeedback,
        updateEarlyAccessFeatureEnrollment,
        copyExternalFeaturePreviewLink,
    } = useActions(featurePreviewsLogic)
    const { submitEarlyAccessFeatureFeedback } = useAsyncActions(featurePreviewsLogic)

    const { flagKey, enabled, name, description, documentationUrl } = feature
    const isFeedbackActive = activeFeedbackFlagKey === flagKey

    const [feedback, setFeedback] = useState('')

    return (
        <PreviewCard
            feature={feature}
            title={
                <div className="flex items-center gap-1">
                    <Label className="flex items-center gap-2 cursor-pointer" htmlFor={`${feature.flagKey}-switch`}>
                        <LemonSwitch
                            checked={enabled}
                            onChange={(newChecked) =>
                                updateEarlyAccessFeatureEnrollment(flagKey, newChecked, feature.stage)
                            }
                            id={`${feature.flagKey}-switch`}
                        />
                        <h4 className="font-bold mb-0">{name}</h4>
                    </Label>
                    <LemonButton
                        icon={<IconLink />}
                        size="xsmall"
                        onClick={() => copyExternalFeaturePreviewLink(flagKey)}
                    />
                </div>
            }
            description={
                <div className="flex flex-col gap-2 max-w-prose">
                    <p className="m-0">{description || <span className="text-tertiary">No description</span>}</p>
                    {warning && <LemonBanner type="warning">{warning}</LemonBanner>}
                </div>
            }
            actions={
                <div className="flex flex-col gap-2">
                    <div className="whitespace-nowrap">
                        {documentationUrl && (
                            <Link to={documentationUrl} target="_blank">
                                Learn more
                            </Link>
                        )}
                        {!isFeedbackActive && documentationUrl && <span>&nbsp;•&nbsp;</span>}
                        {!isFeedbackActive && (
                            <Link onClick={() => beginEarlyAccessFeatureFeedback(flagKey)}>Give feedback</Link>
                        )}
                    </div>
                </div>
            }
        >
            {isFeedbackActive && (
                <div className="flex flex-col gap-2 max-w-prose">
                    <LemonTextArea
                        autoFocus
                        placeholder={`What's your experience with ${name} been like?`}
                        className="mt-2"
                        value={feedback}
                        onChange={(value) => setFeedback(value)}
                        onKeyDown={(e) => {
                            if (e.key === 'Enter' && e.metaKey) {
                                void submitEarlyAccessFeatureFeedback(feedback).then(() => {
                                    setFeedback('')
                                })
                            } else if (e.key === 'Escape') {
                                cancelEarlyAccessFeatureFeedback()
                                setFeedback('')
                                e.stopPropagation() // Don't close the modal
                            }
                        }}
                    />
                    <div className="flex items-center gap-2">
                        <LemonButton
                            type="secondary"
                            onClick={() => {
                                cancelEarlyAccessFeatureFeedback()
                                setFeedback('')
                            }}
                        >
                            Cancel
                        </LemonButton>
                        <LemonButton
                            type="primary"
                            onClick={() => {
                                void submitEarlyAccessFeatureFeedback(feedback).then(() => {
                                    setFeedback('')
                                })
                            }}
                            loading={activeFeedbackFlagKeyLoading}
                            className="flex-1"
                            center
                        >
                            Submit feedback
                        </LemonButton>
                    </div>
                </div>
            )}
        </PreviewCard>
    )
}
