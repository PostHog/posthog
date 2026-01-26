import { BindLogic, useActions, useValues } from 'kea'
import { useEffect, useRef } from 'react'

import { IconBrowser, IconDownload } from '@posthog/icons'
import { LemonTag, Spinner } from '@posthog/lemon-ui'

import { appEditorUrl } from 'lib/components/AuthorizedUrlList/authorizedUrlListLogic'
import { HeatmapCanvas } from 'lib/components/heatmaps/HeatmapCanvas'
import { FilmCameraHog } from 'lib/components/hedgehogs'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner/LemonBanner'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LoadingBar } from 'lib/lemon-ui/LoadingBar'
import { FilterPanel } from 'scenes/heatmaps/components/FilterPanel'
import { HeatmapHeader } from 'scenes/heatmaps/components/HeatmapHeader'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneDivider } from '~/layout/scenes/components/SceneDivider'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { heatmapLogic } from './heatmapLogic'

export function HeatmapScene({ id }: { id: string }): JSX.Element {
    const logicProps = { id: id }
    const logic = heatmapLogic(logicProps)

    const {
        name,
        loading,
        type,
        displayUrl,
        widthOverride,
        heightOverride,
        screenshotUrl,
        generatingScreenshot,
        screenshotLoaded,
        containerWidth,
        desiredNumericWidth,
        effectiveWidth,
        scalePercent,
        imageUrl,
        uploadedImageWidth,
        uploadScalePercent,
    } = useValues(logic)
    const {
        setName,
        updateHeatmap,
        onIframeLoad,
        setScreenshotLoaded,
        exportHeatmap,
        setContainerWidth,
        setUploadedImageWidth,
    } = useActions(logic)

    const measureRef = useRef<HTMLDivElement | null>(null)
    useEffect(() => {
        const measure = (): void => {
            if (measureRef.current) {
                const w = measureRef.current.getBoundingClientRect().width
                setContainerWidth(typeof w === 'number' ? w : null)
            }
        }
        measure()
        const onResize = (): void => {
            measure()
        }
        window.addEventListener('resize', onResize)
        return () => {
            window.removeEventListener('resize', onResize)
        }
    }, [setContainerWidth, widthOverride])

    if (loading) {
        return (
            <SceneContent>
                <Spinner />
            </SceneContent>
        )
    }

    return (
        <BindLogic logic={heatmapLogic} props={logicProps}>
            <SceneContent>
                <SceneTitleSection
                    name={name || 'No name'}
                    resourceType={{
                        type: 'heatmap',
                    }}
                    description={null}
                    canEdit
                    onNameChange={setName}
                    forceBackTo={{
                        name: 'Heatmaps',
                        path: urls.heatmaps(),
                        key: 'heatmaps',
                    }}
                    actions={
                        <>
                            <LemonButton type="primary" onClick={updateHeatmap} size="small" data-attr="save-heatmap">
                                Save
                            </LemonButton>
                            <LemonButton
                                onClick={exportHeatmap}
                                data-attr="export-heatmap"
                                type="secondary"
                                icon={<IconDownload />}
                                size="small"
                                tooltip="Export heatmap as PNG"
                                tooltipPlacement="bottom"
                                disabledReason={
                                    (type === 'screenshot' && !screenshotUrl) || (type === 'upload' && !imageUrl)
                                        ? 'Image is not ready'
                                        : undefined
                                }
                            >
                                Export{' '}
                                <LemonTag type="warning" className="ml-2">
                                    BETA
                                </LemonTag>
                            </LemonButton>
                        </>
                    }
                />
                <LemonBanner
                    type="info"
                    dismissKey={`heatmap-type-info:${id}:${type ?? 'unknown'}`}
                    className="mb-2"
                    action={
                        type !== 'upload'
                            ? {
                                  size: 'small',
                                  type: 'secondary',
                                  children: 'Open in toolbar',
                                  to: displayUrl
                                      ? appEditorUrl(displayUrl, {
                                            userIntent: 'heatmaps',
                                        })
                                      : undefined,
                                  targetBlank: true,
                                  'data-attr': 'heatmaps-open-in-toolbar',
                                  disabledReason: !displayUrl ? 'Select a URL first' : undefined,
                              }
                            : undefined
                    }
                >
                    {type === 'upload' ? (
                        <>
                            You're viewing an <LemonTag type="highlight">Uploaded image</LemonTag> heatmap. The heatmap
                            data is matched using the data URL pattern you specified.
                        </>
                    ) : (
                        <>
                            You're viewing {type === 'screenshot' ? 'a' : 'an'}{' '}
                            <LemonTag type="highlight">{type === 'screenshot' ? 'Screenshot' : 'Iframe'}</LemonTag>{' '}
                            heatmap. We recommend trying both methods to see which works best for your site. You can
                            also open your website using the toolbar and verify results there (useful for auth-protected
                            pages).
                        </>
                    )}
                </LemonBanner>
                <HeatmapHeader />
                <FilterPanel hideViewportChooser={type === 'upload'} />
                <SceneDivider />
                <div ref={measureRef} className="w-full">
                    <div
                        className="border mx-auto bg-white rounded-lg"
                        style={{
                            // For upload: use image width if smaller than container, otherwise constrain to container
                            // For others: use the selected viewport width (effectiveWidth)
                            width:
                                type === 'upload'
                                    ? uploadedImageWidth && containerWidth && uploadedImageWidth < containerWidth
                                        ? uploadedImageWidth
                                        : undefined
                                    : (effectiveWidth ?? '100%'),
                            maxWidth: type === 'upload' ? '100%' : undefined,
                        }}
                    >
                        <div className="p-2 border-b text-muted-foreground gap-x-2 flex items-center">
                            <IconBrowser /> {type === 'upload' ? 'Uploaded image' : displayUrl}
                            {type === 'upload' &&
                            uploadedImageWidth &&
                            containerWidth &&
                            uploadedImageWidth > containerWidth ? (
                                <LemonTag className="ml-auto" type="highlight">
                                    Scaled to {uploadScalePercent}% ({uploadedImageWidth}px →{' '}
                                    {Math.round(containerWidth)} px)
                                </LemonTag>
                            ) : type !== 'upload' &&
                              typeof widthOverride === 'number' &&
                              containerWidth &&
                              widthOverride > containerWidth ? (
                                <LemonTag className="ml-auto" type="highlight">
                                    Scaled to {scalePercent}% ({widthOverride}px →{' '}
                                    {Math.round(effectiveWidth as number)} px)
                                </LemonTag>
                            ) : null}
                        </div>
                        {type === 'screenshot' && (
                            <div className="relative flex w-full justify-center flex-1" style={{ width: '100%' }}>
                                {generatingScreenshot ? (
                                    <div className="flex-1 flex items-center justify-center min-h-96">
                                        <style>{`@keyframes hog-wobble{from{transform:rotate(0deg)}to{transform:rotate(5deg)}}`}</style>
                                        <div className="text-sm text-center font-semibold">
                                            <FilmCameraHog
                                                className="w-32 h-32 mx-auto mb-2"
                                                style={{
                                                    animation: 'hog-wobble 1.2s ease-in-out infinite alternate',
                                                    transformOrigin: '50% 50%',
                                                }}
                                            />
                                            Taking screenshots of your page...
                                            <div className="text-muted text-xs mt-2">
                                                This usually takes a few minutes
                                            </div>
                                            <LoadingBar />
                                        </div>
                                    </div>
                                ) : screenshotUrl ? (
                                    <>
                                        {screenshotLoaded && (
                                            <HeatmapCanvas
                                                key={effectiveWidth ?? 'auto'}
                                                positioning="absolute"
                                                widthOverride={desiredNumericWidth ?? undefined}
                                                context="in-app"
                                            />
                                        )}
                                        <img
                                            id="heatmap-screenshot"
                                            src={screenshotUrl}
                                            style={{ width: '100%', height: 'auto', display: 'block' }}
                                            onLoad={() => setScreenshotLoaded(true)}
                                            onError={() => console.error('Failed to load image')}
                                            className="rounded-b-lg border-l border-r border-b"
                                        />
                                    </>
                                ) : null}
                            </div>
                        )}
                        {type === 'upload' && imageUrl && (
                            <div className="relative flex w-full justify-center flex-1" style={{ width: '100%' }}>
                                {screenshotLoaded && (
                                    <HeatmapCanvas
                                        key={uploadedImageWidth ?? 'auto'}
                                        positioning="absolute"
                                        widthOverride={uploadedImageWidth ?? undefined}
                                        context="in-app"
                                    />
                                )}
                                <img
                                    id="heatmap-screenshot"
                                    src={imageUrl}
                                    onLoad={(e) => {
                                        const img = e.target as HTMLImageElement
                                        if (img.naturalWidth) {
                                            setUploadedImageWidth(img.naturalWidth)
                                        }
                                        setScreenshotLoaded(true)
                                    }}
                                    onError={() => console.error('Failed to load image')}
                                    className="rounded-b-lg border-l border-r border-b max-w-full max-h-full"
                                />
                            </div>
                        )}
                        {type === 'iframe' && (
                            <div
                                className="relative"
                                // eslint-disable-next-line react/forbid-dom-props
                                style={{ height: heightOverride }}
                            >
                                <HeatmapCanvas
                                    positioning="absolute"
                                    widthOverride={desiredNumericWidth ?? undefined}
                                    context="in-app"
                                />
                                <iframe
                                    id="heatmap-iframe"
                                    className="bg-white rounded-b-lg"
                                    // eslint-disable-next-line react/forbid-dom-props
                                    style={{ width: '100%', height: heightOverride }}
                                    src={displayUrl || ''}
                                    onLoad={onIframeLoad}
                                    sandbox="allow-scripts allow-same-origin"
                                    allow=""
                                />
                            </div>
                        )}
                    </div>
                </div>
            </SceneContent>
        </BindLogic>
    )
}
