import { useActions, useValues } from 'kea'
import { useDebouncedCallback } from 'use-debounce'

import { IconLaptop, IconTabletLandscape, IconTabletPortrait } from '@posthog/icons'
import { Spinner } from '@posthog/lemon-ui'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { LemonRadio } from 'lib/lemon-ui/LemonRadio'
import { LemonSegmentedSelect } from 'lib/lemon-ui/LemonSegmentedSelect'
import { IconPhone } from 'lib/lemon-ui/icons'
import { InvalidURL } from 'scenes/heatmaps/components/HeatmapsBrowser'
import { urls } from 'scenes/urls'

import { ScenePanelDivider } from '~/layout/scenes/SceneLayout'
import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneDivider } from '~/layout/scenes/components/SceneDivider'
import { SceneSection } from '~/layout/scenes/components/SceneSection'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { heatmapLogic } from './heatmapLogic'

export function HeatmapNewScene(): JSX.Element {
    const logic = new heatmapLogic({ id: 'new' })
    const { loading, displayUrl, isDisplayUrlValid, type, name, width } = useValues(logic)
    const { setDisplayUrl, setType, setName, createHeatmap, setWidth } = useActions(logic)

    const widthOptions = [
        {
            value: 320,
            icon: <IconPhone />,
        },
        {
            value: 375,
            icon: <IconPhone />,
        },
        {
            value: 425,
            icon: <IconPhone />,
        },
        {
            value: 768,
            icon: <IconTabletPortrait />,
        },
        {
            value: 1024,
            icon: <IconTabletLandscape />,
        },
        {
            value: 1440,
            icon: <IconLaptop />,
        },
        {
            value: 1920,
            icon: <IconLaptop />,
        },
    ]

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
            <SceneSection title="URL of heatmap" description="URL to your website">
                <LemonInput value={displayUrl || ''} onChange={setDisplayUrl} placeholder="https://www.example.com" />
                {!isDisplayUrlValid ? <InvalidURL /> : null}
            </SceneSection>
            <SceneDivider />
            <SceneSection title="Type of heatmap" description="Select the type of heatmap you want to create">
                <LemonRadio
                    options={[
                        {
                            label: 'Screenshot',
                            value: 'screenshot',
                            description: 'We will generate a full screenshot of your website',
                        },
                        {
                            label: 'Iframe',
                            value: 'iframe',
                            description:
                                'We will load your website in an iframe. Make sure you allow your website to be loaded in an iframe.',
                        },
                    ]}
                    value={type}
                    onChange={(value: string) => setType(value)}
                />
            </SceneSection>
            <SceneDivider />
            <SceneSection title="Viewport width" description="Width of the viewport to capture">
                <LemonSegmentedSelect
                    options={widthOptions.map((option) => ({
                        label: `${option.value}px`,
                        value: option.value,
                        icon: option.icon,
                    }))}
                    value={width}
                    onChange={(value: number) => setWidth(value)}
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
                    disabledReason={!isDisplayUrlValid ? 'Invalid URL' : !displayUrl ? 'URL is required' : null}
                >
                    Save
                </LemonButton>
            </div>
        </SceneContent>
    )
}
