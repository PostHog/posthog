import { useActions, useValues } from 'kea'
import { useDebouncedCallback } from 'use-debounce'

import { Spinner } from '@posthog/lemon-ui'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { LemonRadio } from 'lib/lemon-ui/LemonRadio'
import { HeatmapsForbiddenURL } from 'scenes/heatmaps/components/HeatmapsForbiddenURL'
import { HeatmapsUrlsList } from 'scenes/heatmaps/components/HeatmapsInfo'
import { HeatmapsInvalidURL } from 'scenes/heatmaps/components/HeatmapsInvalidURL'
import { urls } from 'scenes/urls'

import { ScenePanelDivider } from '~/layout/scenes/SceneLayout'
import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneDivider } from '~/layout/scenes/components/SceneDivider'
import { SceneSection } from '~/layout/scenes/components/SceneSection'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { HeatmapType } from '~/types'

import { heatmapLogic } from './heatmapLogic'

export function HeatmapNewScene(): JSX.Element {
    const logic = heatmapLogic({ id: 'new' })
    const { loading, displayUrl, isDisplayUrlValid, type, name, dataUrl, isBrowserUrlAuthorized } = useValues(logic)
    const { setDisplayUrl, setType, setName, createHeatmap, setDataUrl } = useActions(logic)

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
            <ScenePanelDivider />
            <SceneSection title="Page URL" description="URL to your website">
                <LemonInput value={displayUrl || ''} onChange={setDisplayUrl} placeholder="https://www.example.com" />
                {!isDisplayUrlValid ? <HeatmapsInvalidURL /> : null}
                {!displayUrl && <HeatmapsUrlsList />}
            </SceneSection>
            <SceneDivider />
            <SceneSection
                title="Heatmap data URL"
                description="An exact match or a pattern for heatmap data. For example, use a pattern if you have pages with dynamic IDs. E.g. https://www.example.com/users/* will aggregate data from all pages under /users/."
            >
                <LemonInput
                    size="small"
                    placeholder="https://www.example.com/*"
                    value={dataUrl ?? ''}
                    onChange={(value) => {
                        setDataUrl(value || null)
                    }}
                    fullWidth={true}
                />
                <div className="text-xs text-muted mt-1">Add * for wildcards to aggregate data from multiple pages</div>
                {dataUrl && !isBrowserUrlAuthorized ? <HeatmapsForbiddenURL /> : null}
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
            </SceneSection>
            <SceneDivider />
            <div className="flex gap-2">
                <LemonButton
                    className="w-fit"
                    type="primary"
                    data-attr="save-heatmap"
                    onClick={createHeatmap}
                    loading={false}
                    disabledReason={
                        !isDisplayUrlValid || !isBrowserUrlAuthorized
                            ? 'Invalid URL or forbidden URL'
                            : !displayUrl
                              ? 'URL is required'
                              : !dataUrl
                                ? 'Heatmap data URL is required'
                                : null
                    }
                >
                    Save
                </LemonButton>
            </div>
        </SceneContent>
    )
}
