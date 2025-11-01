import { useValues } from 'kea'
import { useMemo, useState } from 'react'

import { IconGear, IconPlusSmall } from '@posthog/icons'
import { LemonButton, LemonTable, LemonTabs, LemonTabsProps } from '@posthog/lemon-ui'

import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { Scene, SceneExport } from 'scenes/sceneTypes'
import { sceneConfigurations } from 'scenes/scenes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneDivider } from '~/layout/scenes/components/SceneDivider'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { exampleAppLogic } from './exampleAppLogic'

type ExampleAppTabs = 'main' | 'secondary'

export interface ExampleAppMockPerson {
    id: string
    name: string
    description?: string
    createdAt: string
    updatedAt: string
}
function ExampleAppIndexTab({ tabId }: { tabId: string }): JSX.Element {
    const { persons, personsLoading } = useValues(exampleAppLogic({ tabId: tabId }))

    return (
        <LemonTable
            loading={personsLoading}
            columns={[
                {
                    title: 'Name',
                    dataIndex: 'name',
                    sorter: (a, b) => a.name.split(' ')[1].localeCompare(b.name.split(' ')[1]),
                    render: (_, item) => (
                        <LemonTableLink
                            title={item.name}
                            to={urls.exampleAppDetail(item.id)}
                            description={item.description || `${item.name} was created at ${item.createdAt}`}
                        />
                    ),
                },
                {
                    title: 'Created at',
                    dataIndex: 'createdAt',
                    tooltip: 'When the resource was created.',
                    sorter: (a, b) => a.createdAt.localeCompare(b.createdAt),
                },
                {
                    title: 'Updated at',
                    key: 'updatedAt',
                    render: (_, person) => `${person.updatedAt}`,
                },
            ]}
            dataSource={persons}
        />
    )
}
function ExampleAppSecondTab(): JSX.Element {
    return <div>Example app second tab</div>
}
function ConfigureSettingsButton(): JSX.Element {
    return (
        <LemonButton size="small" type="secondary" icon={<IconGear />}>
            Configure/Settings
        </LemonButton>
    )
}
function MainCallToActionButton(): JSX.Element {
    return (
        <LemonButton size="small" type="primary" icon={<IconPlusSmall />} to={urls.exampleAppDetail('new')}>
            Create new item
        </LemonButton>
    )
}

interface ExampleAppSceneProps {
    tabId?: string
}
export const scene: SceneExport = {
    component: ExampleAppScene,
    logic: exampleAppLogic,
}
export function ExampleAppScene({ tabId }: ExampleAppSceneProps = {}): JSX.Element {
    const [activeTab, setActiveTab] = useState<ExampleAppTabs>('main')

    const tabs: LemonTabsProps<ExampleAppTabs>['tabs'] = [
        {
            key: 'main',
            label: 'Main list view',
            content: <ExampleAppIndexTab tabId={tabId || 'default'} />,
            tooltip: 'Use tab tooltips to explain what the tab is about',
        },
        {
            key: 'secondary',
            label: 'Secondary list view',
            content: <ExampleAppSecondTab />,
            tooltip: 'Or use tooltipDocLink to link to a docs page',
            tooltipDocLink: 'https://posthog.com/docs/libraries/react',
        },
    ]

    // UX TIP: We change main call to actions based on active tab
    const actions = useMemo(() => {
        if (activeTab === 'main') {
            return (
                <>
                    {/* UX TIP: We want to make all main navigation buttons secondary, and only have one primary button */}
                    {/* UX TIP: We put the main call to action on the further right to make it more visible, and the secondary call to actions on the left */}
                    <ConfigureSettingsButton />
                    <MainCallToActionButton />
                </>
            )
        }
        return (
            <>
                <ConfigureSettingsButton />
            </>
        )
    }, [activeTab])

    // Wrap everything in a SceneContent component
    return (
        <SceneContent>
            <SceneTitleSection
                name={sceneConfigurations[Scene.ExampleApp].name}
                description={sceneConfigurations[Scene.ExampleApp].description}
                resourceType={{
                    // The type correlates to the iconTypes defined in the defaultTree.tsx file,
                    // there you can define the icon and the colors
                    type: sceneConfigurations[Scene.ExampleApp].iconType || 'default_icon_type',

                    // We can force an icon to be displayed by setting the forceIcon prop
                    // forceIcon: <Icon123 />
                    // forceIconColorOverride: ['var(--light-color-defined-in-base-scss)', 'var(--dark-color-defined-in-base-scss)']
                }}
                actions={actions}
            />
            {/* We can use the SceneDivider component to add a divider between the title section and the rest of the scene */}
            <SceneDivider />

            {/* UX TIP: Tabs in a scene should act as a filter, not as a navigation tool */}
            <LemonTabs
                sceneInset // Important: This makes the tabs take the full width of the scene
                activeKey={activeTab}
                onChange={setActiveTab}
                tabs={tabs}
            />
        </SceneContent>
    )
}
