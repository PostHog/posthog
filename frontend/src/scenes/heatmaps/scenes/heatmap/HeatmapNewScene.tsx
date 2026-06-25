import { useActions, useValues } from 'kea'
import { useDebouncedCallback } from 'use-debounce'

import { Spinner } from '@posthog/lemon-ui'

import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonInputSelect } from 'lib/lemon-ui/LemonInputSelect/LemonInputSelect'
import { LemonRadio } from 'lib/lemon-ui/LemonRadio'
import { Link } from 'lib/lemon-ui/Link'
import { HeatmapAdvancedSettings } from 'scenes/heatmaps/components/HeatmapAdvancedSettings'
import { heatmapsBrowserLogic } from 'scenes/heatmaps/components/heatmapsBrowserLogic'
import { HeatmapsInvalidURL } from 'scenes/heatmaps/components/HeatmapsInvalidURL'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneDivider } from '~/layout/scenes/components/SceneDivider'
import { SceneSection } from '~/layout/scenes/components/SceneSection'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { HeatmapType } from '~/types'

import { heatmapLogic } from './heatmapLogic'

export function HeatmapNewScene(): JSX.Element {
    const logic = heatmapLogic({ id: 'new' })
    const { loading, displayUrl, isDisplayUrlValid, type, name, dataUrl, isBrowserUrlAuthorized, displayUrlIsPattern } =
        useValues(logic)
    const { setDisplayUrl, setType, setName, createHeatmap } = useActions(logic)
    const { topUrls, topUrlsLoading, noPageviews } = useValues(heatmapsBrowserLogic)

    const debouncedOnNameChange = useDebouncedCallback((name: string) => {
        setName(name)
    }, 500)

    if (loading) {
        return (
            <SceneContent>
                <Spinner />
            </SceneContent>
        )
    }

    return (
        <SceneContent>
            <SceneTitleSection
                name={name}
                resourceType={{
                    type: 'heatmap',
                }}
                description={null}
                canEdit
                forceEdit
                onNameChange={debouncedOnNameChange}
                forceBackTo={{
                    name: 'Heatmaps',
                    path: urls.heatmaps(),
                    key: 'heatmaps',
                }}
            />
            <SceneSection title="Page URL" description="URL to your website">
                <LemonInputSelect
                    mode="single"
                    allowCustomValues
                    disableEditing
                    fullWidth
                    placeholder="https://www.example.com"
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
                    title={topUrls && topUrls.length > 0 ? 'Most viewed pages' : undefined}
                    popoverClassName="max-w-0"
                    data-attr="heatmap-new-page-url"
                />
                {displayUrl && !isDisplayUrlValid ? (
                    displayUrlIsPattern ? (
                        <LemonBanner type="error" className="mt-2">
                            The page URL can't contain wildcards. Add wildcards to the heatmap data URL below instead.
                        </LemonBanner>
                    ) : (
                        <HeatmapsInvalidURL />
                    )
                ) : null}
                {!displayUrl && noPageviews && !topUrlsLoading ? (
                    <div className="text-xs text-muted mt-1">No pageview events have been received yet.</div>
                ) : null}
            </SceneSection>
            <SceneDivider />
            <SceneSection title="Capture method" description="Choose how to display your page in the heatmap">
                <LemonRadio
                    options={[
                        {
                            label: 'Screenshot',
                            value: 'screenshot',
                            description: 'We will generate a full-page screenshot of your website',
                        },
                        {
                            label: 'Iframe',
                            value: 'iframe',
                            description:
                                'We will load your website in an iframe. Make sure you allow your website to be loaded in an iframe.',
                        },
                    ]}
                    value={type}
                    onChange={(value: HeatmapType) => setType(value)}
                />
                <LemonBanner type="info" className="mb-4">
                    You can also generate a screenshot of your site directly from{' '}
                    <Link to={urls.replay()} target="_blank">
                        session replay
                    </Link>{' '}
                    by clicking the 'view heatmap' button above a recording.
                </LemonBanner>
            </SceneSection>
            <SceneDivider />
            <HeatmapAdvancedSettings
                dataUrlPlaceholderFallback="https://www.example.com/*"
                dataUrlHelp="Defaults to the page URL. Add * for wildcards to aggregate data from multiple pages — e.g. https://www.example.com/users/* aggregates all pages under /users/."
                consentHelp="Ask the browser to close cookie/consent popups before capturing the screenshot. This can slow down or fail the render on some sites, so it's off by default."
                showForbiddenUrl
            />
            <SceneDivider />
            <div className="flex gap-2">
                <LemonButton
                    className="w-fit"
                    type="primary"
                    data-attr="save-heatmap"
                    onClick={createHeatmap}
                    loading={false}
                    disabledReason={
                        !isDisplayUrlValid || (!!dataUrl && !isBrowserUrlAuthorized)
                            ? 'Invalid URL or forbidden URL'
                            : !displayUrl
                              ? 'URL is required'
                              : null
                    }
                >
                    Save
                </LemonButton>
            </div>
        </SceneContent>
    )
}
