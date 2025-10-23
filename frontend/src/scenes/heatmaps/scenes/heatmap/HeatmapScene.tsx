import { BindLogic, useActions, useValues } from 'kea'

import { IconBrowser } from '@posthog/icons'
import { Spinner } from '@posthog/lemon-ui'

import { HeatmapCanvas } from 'lib/components/heatmaps/HeatmapCanvas'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
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

    const { name, loading, type, displayUrl, widthOverride, screenshotUrl, generatingScreenshot, screenshotLoaded } =
        useValues(logic)
    const { setName, updateHeatmap, onIframeLoad, setScreenshotLoaded } = useActions(logic)

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
                                    <div className="text-sm text-muted">
                                        Generating screenshots...
                                        <Spinner />
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
                                        className="rounded-b-lg"
                                        onError={() => {
                                            console.error('Failed to load screenshot')
                                        }}
                                    />
                                </>
                            ) : null}
                        </div>
                    ) : (
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
                    )}
                </div>
            </SceneContent>
        </BindLogic>
    )
}
