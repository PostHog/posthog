import { useActions, useValues } from 'kea'

import { IconCheckCircle, IconWarning } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonCard, LemonLabel, Spinner } from '@posthog/lemon-ui'

import { LemonInputSelect } from 'lib/lemon-ui/LemonInputSelect/LemonInputSelect'
import { LemonRadio } from 'lib/lemon-ui/LemonRadio'
import { cn } from 'lib/utils/css-classes'
import { HeatmapAdvancedSettings } from 'scenes/heatmaps/components/HeatmapAdvancedSettings'
import { HeatmapRecording } from 'scenes/heatmaps/components/HeatmapRecording'
import { HeatmapRecordingFallback } from 'scenes/heatmaps/components/HeatmapRecordingFallback'
import { heatmapsBrowserLogic, isUrlPattern } from 'scenes/heatmaps/components/heatmapsBrowserLogic'
import { HeatmapsEnableCapture } from 'scenes/heatmaps/components/HeatmapsEnableCapture'
import { HeatmapsInvalidURL } from 'scenes/heatmaps/components/HeatmapsInvalidURL'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { HeatmapType } from '~/types'

import { HeatmapCreationStep, heatmapCreationLogic } from './heatmapCreationLogic'
import { heatmapLogic } from './heatmapLogic'

const CREATION_STEPS: { key: HeatmapCreationStep; label: string }[] = [
    { key: 'page', label: 'Choose page' },
    { key: 'background', label: 'Choose background' },
    { key: 'review', label: 'Review and create' },
]

function HeatmapCreationStepper(): JSX.Element {
    const { currentStep, furthestStep, pageAccess, recordingHeatmapOpen } = useValues(heatmapCreationLogic)
    const { navigateToStep } = useActions(heatmapCreationLogic)
    const currentIndex = CREATION_STEPS.findIndex(({ key }) => key === currentStep)
    const furthestIndex = CREATION_STEPS.findIndex(({ key }) => key === furthestStep)

    return (
        <nav className="flex items-center justify-center mb-6" aria-label="Heatmap creation progress">
            {CREATION_STEPS.map((step, index) => {
                const isCompleted = index < currentIndex
                const isCurrent = step.key === currentStep
                const isAvailable = index <= furthestIndex
                const label =
                    step.key === 'review' && recordingHeatmapOpen
                        ? 'Explore heatmap'
                        : step.key === 'review' && pageAccess === 'login'
                          ? 'Review background'
                          : step.label

                return (
                    <div key={step.key} className="flex items-center">
                        {index > 0 ? (
                            <div
                                className={cn(
                                    'w-6 h-px transition-colors',
                                    index <= currentIndex ? 'bg-success' : 'bg-border-primary'
                                )}
                            />
                        ) : null}
                        <button
                            type="button"
                            onClick={() => navigateToStep(step.key)}
                            disabled={!isAvailable}
                            className={cn(
                                'flex items-center gap-1.5 px-2 py-1 rounded transition-colors',
                                isAvailable && 'hover:bg-fill-button-tertiary-hover cursor-pointer',
                                !isAvailable && 'cursor-not-allowed opacity-60'
                            )}
                            aria-current={isCurrent ? 'step' : undefined}
                        >
                            {isCompleted ? (
                                <IconCheckCircle className="size-5 text-success" />
                            ) : (
                                <span
                                    className={cn(
                                        'flex items-center justify-center size-5 rounded-full text-xs font-semibold',
                                        isCurrent
                                            ? 'bg-accent text-primary-inverse ring-2 ring-accent/25'
                                            : 'bg-surface-secondary text-secondary border border-primary'
                                    )}
                                >
                                    {index + 1}
                                </span>
                            )}
                            <span
                                className={cn('text-sm', isCurrent ? 'font-semibold text-primary' : 'text-secondary')}
                            >
                                {label}
                            </span>
                        </button>
                    </div>
                )
            })}
        </nav>
    )
}

function CaptureReadiness(): JSX.Element {
    const { captureEnabled } = useValues(heatmapCreationLogic)

    return captureEnabled ? (
        <div className="flex items-center gap-2 text-success">
            <IconCheckCircle className="size-5 shrink-0" />
            <span>Heatmap capture is enabled for this project.</span>
        </div>
    ) : (
        <LemonBanner type="warning">
            <div className="flex flex-col gap-3">
                <div>
                    Heatmap capture is off for this project. You can still create this heatmap, but it will remain empty
                    until capture is enabled.
                </div>
                <HeatmapsEnableCapture />
            </div>
        </LemonBanner>
    )
}

function MatchingDataReadiness(): JSX.Element {
    const { currentPageDataCheck, pageDataCheckLoading } = useValues(heatmapCreationLogic)
    const { requestPageDataCheck } = useActions(heatmapCreationLogic)

    if (pageDataCheckLoading) {
        return (
            <div className="flex items-center gap-2 text-muted">
                <Spinner /> Checking for matching heatmap data from the last 30 days
            </div>
        )
    }

    if (!currentPageDataCheck) {
        return (
            <div className="flex items-center gap-2 text-muted">
                <IconWarning className="size-5 shrink-0" />
                Enter a valid page and heatmap data URL to check for matching data.
            </div>
        )
    }

    if (currentPageDataCheck.outcome === 'detected') {
        return (
            <div className="flex items-center gap-2 text-success">
                <IconCheckCircle className="size-5 shrink-0" />
                <span>
                    Found {currentPageDataCheck.count?.toLocaleString()} matching interaction
                    {currentPageDataCheck.count === 1 ? '' : 's'} from the last 30 days.
                </span>
            </div>
        )
    }

    const checkAgain = {
        children: 'Check again',
        onClick: () => requestPageDataCheck('manual'),
    }

    return (
        <LemonBanner type="warning" action={checkAgain}>
            {currentPageDataCheck.outcome === 'none'
                ? 'No matching heatmap data was found in the last 30 days. You can create the heatmap now and collect data later.'
                : "We couldn't check for matching data. You can try again or continue creating the heatmap."}
        </LemonBanner>
    )
}

function ChoosePageStep(): JSX.Element {
    const logic = heatmapLogic({ id: 'new' })
    const { displayUrl, isDisplayUrlValid, displayUrlIsPattern, dataUrl } = useValues(logic)
    const { setDisplayUrl } = useActions(logic)
    const { topUrls, topUrlsLoading, noPageviews } = useValues(heatmapsBrowserLogic)
    const { pageStepBlockReason } = useValues(heatmapCreationLogic)
    const { continueFromPage } = useActions(heatmapCreationLogic)

    return (
        <LemonCard hoverEffect={false} className="max-w-3xl mx-auto">
            <div className="flex flex-col gap-6">
                <div>
                    <h2 className="mb-1">Choose a page</h2>
                    <p className="text-muted mb-0">
                        Pick the page to display behind the heatmap. We'll also check whether it is ready to collect and
                        show interaction data.
                    </p>
                </div>
                <div>
                    <LemonLabel>Page URL</LemonLabel>
                    <LemonInputSelect
                        mode="single"
                        allowCustomValues
                        disableEditing
                        fullWidth
                        placeholder="https://www.example.com/pricing"
                        loading={topUrlsLoading}
                        value={displayUrl ? [displayUrl] : []}
                        onChange={(next) => setDisplayUrl(next[0] ?? '')}
                        options={(topUrls ?? []).map(({ url }) => ({
                            key: url,
                            label: url,
                            labelComponent: (
                                <span className="block min-w-0 max-w-full truncate ph-no-capture" title={url}>
                                    {url}
                                </span>
                            ),
                        }))}
                        title={topUrls?.length ? 'Most viewed pages' : undefined}
                        popoverClassName="max-w-0"
                        data-attr="heatmap-new-page-url"
                    />
                    {displayUrl && !isDisplayUrlValid ? (
                        displayUrlIsPattern ? (
                            <LemonBanner type="error" className="mt-2">
                                The page URL can't contain wildcards. Add wildcards to the heatmap data URL below.
                            </LemonBanner>
                        ) : (
                            <HeatmapsInvalidURL />
                        )
                    ) : null}
                    {!displayUrl && noPageviews && !topUrlsLoading ? (
                        <div className="text-xs text-muted mt-1">
                            No pageview events have been received yet. You can enter a URL manually.
                        </div>
                    ) : null}
                </div>

                <div className="flex flex-col gap-3">
                    <h3 className="mb-0">Readiness</h3>
                    <CaptureReadiness />
                    <MatchingDataReadiness />
                </div>

                <HeatmapAdvancedSettings
                    dataUrlPlaceholderFallback="https://www.example.com/*"
                    dataUrlHelp="Defaults to the page URL. Add * to combine data from multiple pages, for example https://www.example.com/users/*."
                    consentHelp={null}
                    showDataUrl
                    showConsent={false}
                    header="Heatmap data URL"
                />
                {dataUrl && pageStepBlockReason?.includes('heatmap data URL') ? (
                    <LemonBanner type="error">Enter a complete URL including http:// or https://.</LemonBanner>
                ) : null}

                <div className="flex justify-end">
                    <LemonButton
                        type="primary"
                        onClick={continueFromPage}
                        disabledReason={pageStepBlockReason}
                        data-attr="heatmap-creation-continue-page"
                    >
                        Continue
                    </LemonButton>
                </div>
            </div>
        </LemonCard>
    )
}

function PublicBackgroundChoice(): JSX.Element {
    const logic = heatmapLogic({ id: 'new' })
    const { type } = useValues(logic)
    const { setType } = useActions(logic)
    const { isDisplayUrlAuthorized, authorizationDisabledReason } = useValues(heatmapCreationLogic)
    const { authorizeDisplayUrl } = useActions(heatmapCreationLogic)
    const { currentTeamLoading } = useValues(teamLogic)

    return (
        <div className="flex flex-col gap-4">
            <LemonRadio
                options={[
                    {
                        label: 'Screenshot',
                        value: 'screenshot',
                        description:
                            'A headless browser captures the public page. Pages that require login may show the login screen.',
                    },
                    {
                        label: 'Iframe',
                        value: 'iframe',
                        description:
                            'Loads the page live. It must allow embedding and cannot use your signed-in browser session.',
                    },
                ]}
                value={type}
                onChange={(value: HeatmapType) => setType(value)}
            />

            {type === 'iframe' && !isDisplayUrlAuthorized ? (
                <LemonBanner type="warning">
                    <div className="flex flex-col gap-3">
                        <div>
                            The page URL's origin must be authorized before PostHog can embed it. Screenshot does not
                            require authorization.
                        </div>
                        {authorizationDisabledReason ? (
                            <div className="text-sm">
                                Ask a web analytics editor to authorize this URL, or choose Screenshot.
                            </div>
                        ) : (
                            <LemonButton
                                type="secondary"
                                size="small"
                                className="w-fit"
                                onClick={authorizeDisplayUrl}
                                loading={currentTeamLoading}
                                data-attr="heatmap-authorize-display-url"
                            >
                                Authorize this URL
                            </LemonButton>
                        )}
                    </div>
                </LemonBanner>
            ) : null}

            {type === 'screenshot' ? (
                <HeatmapAdvancedSettings
                    dataUrlPlaceholderFallback=""
                    dataUrlHelp={null}
                    consentHelp="Ask the browser to close cookie or consent popups before capturing the screenshot. This can slow down or fail the render on some sites, so it is off by default."
                    showDataUrl={false}
                    showConsent
                    header="Screenshot options"
                />
            ) : null}
        </div>
    )
}

function ChooseBackgroundStep(): JSX.Element {
    const logic = heatmapLogic({ id: 'new' })
    const { displayUrl } = useValues(logic)
    const { pageAccess, backgroundStepBlockReason, recordingBackgroundData } = useValues(heatmapCreationLogic)
    const { setPageAccess, continueFromBackground, goBack, markRecordingHandoff, navigateToStep } =
        useActions(heatmapCreationLogic)

    return (
        <LemonCard hoverEffect={false} className="max-w-3xl mx-auto">
            <div className="flex flex-col gap-6">
                <div>
                    <h2 className="mb-1">Choose a background</h2>
                    <p className="text-muted mb-0">
                        Tell us whether visitors need to sign in before they can see this page.
                    </p>
                </div>

                <LemonRadio
                    options={[
                        {
                            label: 'No, this page is public',
                            value: 'public',
                            description: 'Create a saved heatmap using a screenshot or live iframe.',
                        },
                        {
                            label: 'Yes, this page requires login',
                            value: 'login',
                            description: 'Use a session recording so the signed-in page state is available.',
                        },
                    ]}
                    value={pageAccess ?? undefined}
                    onChange={setPageAccess}
                />

                {pageAccess === 'public' ? <PublicBackgroundChoice /> : null}
                {pageAccess === 'login' && displayUrl ? (
                    <div className="flex flex-col gap-4">
                        <LemonBanner type="info">
                            Session recordings preserve the signed-in page state. Choose a recording and we will guide
                            you through selecting the exact moment to use as the background. We will bring that state
                            back here for review before opening the heatmap. Recording backgrounds are not saved.
                        </LemonBanner>
                        <HeatmapRecordingFallback
                            url={displayUrl}
                            showEmptyState
                            guidedSelection
                            onRecordingHandoff={markRecordingHandoff}
                        />
                    </div>
                ) : null}

                <div className="flex justify-between">
                    <LemonButton type="secondary" onClick={goBack}>
                        Back
                    </LemonButton>
                    {pageAccess !== 'login' ? (
                        <LemonButton
                            type="primary"
                            onClick={continueFromBackground}
                            disabledReason={backgroundStepBlockReason}
                            data-attr="heatmap-creation-continue-background"
                        >
                            Continue
                        </LemonButton>
                    ) : recordingBackgroundData ? (
                        <LemonButton type="primary" onClick={() => navigateToStep('review')}>
                            Continue
                        </LemonButton>
                    ) : null}
                </div>
            </div>
        </LemonCard>
    )
}

function ReviewStatus({ warning, children }: { warning?: boolean; children: React.ReactNode }): JSX.Element {
    return (
        <div className={cn('flex items-center gap-2', warning ? 'text-warning' : 'text-success')}>
            {warning ? <IconWarning className="size-5 shrink-0" /> : <IconCheckCircle className="size-5 shrink-0" />}
            <span>{children}</span>
        </div>
    )
}

function RecordingBackgroundPreview({ html }: { html: string }): JSX.Element {
    return (
        <div className="overflow-hidden rounded border bg-surface-secondary">
            <iframe
                srcDoc={html}
                title="Selected session recording background"
                sandbox="allow-same-origin"
                tabIndex={-1}
                className="w-full h-96 border-0 bg-white pointer-events-none ph-no-capture"
            />
        </div>
    )
}

function ReviewStep(): JSX.Element {
    const logic = heatmapLogic({ id: 'new' })
    const { displayUrl, type, loading } = useValues(logic)
    const { createHeatmap } = useActions(logic)
    const {
        captureEnabled,
        hasMatchingData,
        creationContext,
        reviewBlockReason,
        pageAccess,
        recordingBackgroundData,
        effectiveDataUrl,
    } = useValues(heatmapCreationLogic)
    const { goBack, openRecordingHeatmap } = useActions(heatmapCreationLogic)
    const usesRecordingBackground = pageAccess === 'login' && !!recordingBackgroundData

    return (
        <LemonCard hoverEffect={false} className="max-w-3xl mx-auto">
            <div className="flex flex-col gap-6">
                <div>
                    <h2 className="mb-1">{usesRecordingBackground ? 'Review background' : 'Review and create'}</h2>
                    <p className="text-muted mb-0">
                        {usesRecordingBackground
                            ? 'Confirm the page state you selected before opening the heatmap.'
                            : 'Readiness warnings will not stop creation. The heatmap will start showing interactions as data arrives.'}
                    </p>
                </div>

                <dl className="grid grid-cols-[minmax(8rem,auto)_1fr] gap-x-4 gap-y-3">
                    <dt className="font-semibold">Page</dt>
                    <dd className="ph-no-capture break-all">{displayUrl}</dd>
                    <dt className="font-semibold">Matching rule</dt>
                    <dd>
                        <span className="font-medium">
                            {isUrlPattern(effectiveDataUrl ?? '') ? 'Pattern' : 'Exact URL'}:
                        </span>{' '}
                        <span className="ph-no-capture break-all">{effectiveDataUrl}</span>
                    </dd>
                    <dt className="font-semibold">Background</dt>
                    <dd>
                        {usesRecordingBackground
                            ? 'Session recording'
                            : type === 'screenshot'
                              ? 'Screenshot'
                              : 'Iframe'}
                    </dd>
                </dl>

                {recordingBackgroundData ? <RecordingBackgroundPreview html={recordingBackgroundData.html} /> : null}

                <div className="flex flex-col gap-2">
                    <ReviewStatus warning={!captureEnabled}>
                        {captureEnabled ? 'Heatmap capture is enabled.' : 'Heatmap capture is disabled.'}
                    </ReviewStatus>
                    <ReviewStatus warning={hasMatchingData !== true}>
                        {hasMatchingData === true
                            ? 'Matching data was found in the last 30 days.'
                            : hasMatchingData === false
                              ? 'No matching data was found in the last 30 days.'
                              : 'Matching data could not be confirmed.'}
                    </ReviewStatus>
                </div>

                <div className="flex justify-between">
                    <LemonButton type="secondary" onClick={goBack} disabled={!usesRecordingBackground && loading}>
                        Back
                    </LemonButton>
                    {usesRecordingBackground ? (
                        <LemonButton
                            type="primary"
                            onClick={openRecordingHeatmap}
                            disabledReason={reviewBlockReason}
                            data-attr="open-recording-heatmap"
                        >
                            View heatmap
                        </LemonButton>
                    ) : (
                        <LemonButton
                            type="primary"
                            onClick={() => createHeatmap(creationContext)}
                            loading={loading}
                            disabledReason={reviewBlockReason}
                            data-attr="save-heatmap"
                        >
                            Create heatmap
                        </LemonButton>
                    )}
                </div>
            </div>
        </LemonCard>
    )
}

function RecordingHeatmapStep(): JSX.Element {
    const { closeRecordingHeatmap, finishRecordingHeatmap } = useActions(heatmapCreationLogic)

    return (
        <div className="flex flex-col gap-4">
            <LemonCard hoverEffect={false} className="sticky top-0 z-20">
                <div className="flex flex-wrap items-center justify-between gap-4">
                    <div>
                        <h2 className="mb-1">Explore your heatmap</h2>
                        <p className="text-muted mb-0">
                            This temporary heatmap uses the session recording moment you selected. It won't be added to
                            your saved heatmaps.
                        </p>
                    </div>
                    <div className="flex gap-2">
                        <LemonButton type="secondary" onClick={closeRecordingHeatmap}>
                            Back to review
                        </LemonButton>
                        <LemonButton type="primary" onClick={finishRecordingHeatmap}>
                            Finish
                        </LemonButton>
                    </div>
                </div>
            </LemonCard>
            <HeatmapRecording embedded />
        </div>
    )
}

export function HeatmapNewScene(): JSX.Element {
    const logic = heatmapLogic({ id: 'new' })
    const { name } = useValues(logic)
    const { setName } = useActions(logic)
    const { currentStep, recordingHeatmapOpen } = useValues(heatmapCreationLogic)

    return (
        <SceneContent>
            <SceneTitleSection
                name={name}
                resourceType={{ type: 'heatmap' }}
                description={null}
                canEdit
                forceEdit
                onNameChange={setName}
                forceBackTo={{ name: 'Heatmaps', path: urls.heatmaps(), key: 'heatmaps' }}
            />
            <HeatmapCreationStepper />
            {currentStep === 'page' ? <ChoosePageStep /> : null}
            {currentStep === 'background' ? <ChooseBackgroundStep /> : null}
            {currentStep === 'review' ? recordingHeatmapOpen ? <RecordingHeatmapStep /> : <ReviewStep /> : null}
        </SceneContent>
    )
}
