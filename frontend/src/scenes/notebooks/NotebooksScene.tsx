import { useValues } from 'kea'
import { router } from 'kea-router'

import { LemonButton, LemonTabs } from '@posthog/lemon-ui'
import { Button } from '@posthog/quill'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { Shortcut } from 'lib/components/Shortcuts/Shortcut'
import { keyBinds } from 'lib/components/Shortcuts/shortcuts'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { notebooksTableLogic } from 'scenes/notebooks/NotebooksTable/notebooksTableLogic'
import { Scene, SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { notebooksEmptyState } from 'products/notebooks/frontend/emptyState/notebooksEmptyState'
import { ReusableWidgetCatalog } from 'products/notebooks/frontend/ReusableWidgetCatalog/ReusableWidgetCatalog'

import { NotebooksTable } from './NotebooksTable/NotebooksTable'

export const scene: SceneExport = {
    component: NotebooksScene,
    logic: notebooksTableLogic,
    productKey: ProductKey.NOTEBOOKS,
    emptyState: notebooksEmptyState,
}

export function NotebooksScene(): JSX.Element {
    const { searchParams } = useValues(router)
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')
    const activeTab = searchParams.tab === 'widgets' ? 'widgets' : 'notebooks'

    return (
        <SceneContent>
            <SceneTitleSection
                name="Notebooks"
                resourceType={{
                    type: 'notebook',
                }}
                actions={
                    <AccessControlAction
                        resourceType={AccessControlResourceType.Notebook}
                        minAccessLevel={AccessControlLevel.Editor}
                    >
                        <Shortcut
                            name="NewNotebook"
                            keybind={[keyBinds.new]}
                            intent="New notebook"
                            interaction="click"
                            scope={Scene.Notebooks}
                        >
                            {todayRailNav ? (
                                <Button
                                    data-attr="new-notebook"
                                    render={<LinkPrimitive to={urls.notebook('new')} />}
                                    variant="primary"
                                    tooltip="New notebook"
                                >
                                    New notebook
                                </Button>
                            ) : (
                                <LemonButton
                                    size="small"
                                    data-attr="new-notebook"
                                    to={urls.notebook('new')}
                                    type="primary"
                                    tooltip="New notebook"
                                >
                                    New notebook
                                </LemonButton>
                            )}
                        </Shortcut>
                    </AccessControlAction>
                }
            />
            <LemonTabs
                activeKey={activeTab}
                sceneInset
                tabs={[
                    {
                        key: 'notebooks',
                        label: 'Notebooks',
                        link: urls.notebooks(),
                        content: <NotebooksTable />,
                    },
                    {
                        key: 'widgets',
                        label: 'Reusable widgets',
                        link: `${urls.notebooks()}?tab=widgets`,
                        content: <ReusableWidgetCatalog />,
                    },
                ]}
            />
        </SceneContent>
    )
}
