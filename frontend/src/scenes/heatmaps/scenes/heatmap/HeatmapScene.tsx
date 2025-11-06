import { BindLogic, useActions, useValues } from 'kea'

import { IconBrowser, IconDownload } from '@posthog/icons'
import { LemonTag, Spinner } from '@posthog/lemon-ui'

import { HeatmapCanvas } from 'lib/components/heatmaps/HeatmapCanvas'
import { FilmCameraHog } from 'lib/components/hedgehogs'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LoadingBar } from 'lib/lemon-ui/LoadingBar'
import { FilterPanel } from 'scenes/heatmaps/components/FilterPanel'
import { HeatmapHeader } from 'scenes/heatmaps/components/HeatmapHeader'
import { urls } from 'scenes/urls'

import { ScenePanelDivider } from '~/layout/scenes/SceneLayout'
import { SceneContent } from '~/layout/scenes/components/SceneContent'
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
        screenshotUrl,
        generatingScreenshot,
        screenshotLoaded,
        retakerToken,
        retakerTokenExpiresIn,
        retakerTokenWidths,
        uploadingRetaker,
    } = useValues(logic)
    const {
        setName,
        updateHeatmap,
        onIframeLoad,
        setScreenshotLoaded,
        exportHeatmap,
        generateRetakerToken,
        uploadRetakerImage,
    } = useActions(logic)

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
                            <LemonButton type="primary" onClick={updateHeatmap} size="small">
                                Save
                            </LemonButton>
                            <LemonButton
                                onClick={exportHeatmap}
                                type="secondary"
                                icon={<IconDownload />}
                                size="small"
                                tooltip="Export heatmap as PNG"
                                tooltipPlacement="bottom"
                                disabledReason={
                                    type === 'screenshot' && !screenshotUrl ? 'Screenshot is not ready' : undefined
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
                <ScenePanelDivider />
                <HeatmapHeader />
                <FilterPanel />
                <ScenePanelDivider />
                <div className="border mx-auto bg-white rounded-lg" style={{ width: widthOverride ?? '100%' }}>
                    <div className="p-2 border-b text-muted-foreground gap-x-2 flex items-center">
                        <IconBrowser /> {displayUrl}
                    </div>
                    {type === 'screenshot' ? (
                        <div
                            className="relative flex w-full justify-center flex-1"
                            style={{ width: widthOverride ?? '100%' }}
                        >
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
                                        <div className="text-muted text-xs mt-2">This usually takes a few minutes</div>
                                        <LoadingBar />
                                    </div>
                                </div>
                            ) : screenshotUrl ? (
                                <>
                                    {screenshotLoaded && (
                                        <HeatmapCanvas
                                            key={widthOverride ?? 'auto'}
                                            positioning="absolute"
                                            widthOverride={widthOverride}
                                            context="in-app"
                                        />
                                    )}
                                    <img
                                        id="heatmap-screenshot"
                                        src={screenshotUrl}
                                        style={{
                                            maxWidth: widthOverride ?? '100%',
                                            height: 'auto',
                                            display: 'block',
                                        }}
                                        onLoad={() => {
                                            setScreenshotLoaded(true)
                                        }}
                                        className="rounded-b-lg border-l border-r border-b"
                                        onError={() => {
                                            console.error('Failed to load screenshot')
                                        }}
                                    />
                                </>
                            ) : null}
                        </div>
                    ) : type === 'iframe' ? (
                        <div className="relative min-h-screen">
                            <HeatmapCanvas positioning="absolute" widthOverride={widthOverride} context="in-app" />
                            <iframe
                                id="heatmap-iframe"
                                className="min-h-screen bg-white rounded-b-lg"
                                // eslint-disable-next-line react/forbid-dom-props
                                style={{ width: widthOverride ?? '100%' }}
                                src={displayUrl || ''}
                                onLoad={onIframeLoad}
                                // these two sandbox values are necessary so that the site and toolbar can run
                                // this is a very loose sandbox,
                                // but we specify it so that at least other capabilities are denied
                                sandbox="allow-scripts allow-same-origin"
                                // we don't allow things such as camera access though
                                allow=""
                            />
                        </div>
                    ) : (
                        <div className="p-4 text-sm text-muted border-t rounded-b-lg bg-white">
                            <div className="font-semibold mb-2">Browser capture (Retaker)</div>
                            <div className="mb-3">
                                Use Retaker to capture a full-page image in your browser. Best for authenticated pages
                                or sites that block iframes.
                            </div>
                            <div className="flex gap-2 mb-3">
                                <LemonButton type="primary" size="small" onClick={generateRetakerToken}>
                                    Generate token
                                </LemonButton>
                            </div>
                            {retakerToken ? (
                                <div className="space-y-2">
                                    <div>
                                        Token (expires in {retakerTokenExpiresIn ?? 0}s):
                                        <div className="font-mono text-xs break-all bg-muted rounded p-2 mt-1">
                                            {retakerToken}
                                        </div>
                                    </div>
                                    <div>Widths: {retakerTokenWidths?.join(', ') || 'n/a'}</div>
                                    <div className="mt-2">
                                        <div className="font-semibold mb-1">Manual upload (for testing)</div>
                                        <div className="flex items-center gap-2">
                                            <input
                                                type="file"
                                                accept="image/jpeg,image/png"
                                                onChange={(e) => {
                                                    const f = e.target.files?.[0]
                                                    if (f) {
                                                        uploadRetakerImage(f)
                                                        e.currentTarget.value = ''
                                                    }
                                                }}
                                            />
                                            {uploadingRetaker ? (
                                                <LemonButton size="small" type="secondary" loading>
                                                    Uploading…
                                                </LemonButton>
                                            ) : null}
                                        </div>
                                        <div className="text-xs text-muted mt-1">
                                            Uses current width ({widthOverride ?? 1024}px). After upload, the image will
                                            display above.
                                        </div>
                                    </div>
                                    <div className="mt-3">
                                        <div className="font-semibold mb-1">Bookmarklet (placeholder)</div>
                                        <div className="text-xs text-muted">
                                            A production bookmarklet will scroll-and-stitch the page and upload the
                                            result here using the token above. For now, use the manual upload or the
                                            upcoming extension.
                                        </div>
                                    </div>
                                </div>
                            ) : null}
                        </div>
                    )}
                </div>
            </SceneContent>
        </BindLogic>
    )
}
