import { BindLogic, useActions, useMountedLogic, useValues } from 'kea'

import { Skeleton } from '@posthog/quill'

import { NotFound } from 'lib/components/NotFound'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { DashboardV2PanelEditor } from '../editor/DashboardV2PanelEditor'
import { DisplayProvider, displayOf } from '../editor/display'
import { panelEditorLogic } from '../editor/panelEditorLogic'
import { DashboardV2EditablePanelsContext } from '../panel/DashboardV2SamplePanel'
import { DashboardV2DeleteDialog } from './DashboardV2DeleteDialog'
import { DashboardV2EmptyState } from './DashboardV2EmptyState'
import { DashboardV2JsonDialog } from './DashboardV2JsonDialog'
import { DashboardV2LoadError } from './DashboardV2LoadError'
import { dashboardV2Logic } from './dashboardV2Logic'
import { DashboardV2SceneMenuBar } from './DashboardV2SceneMenuBar'
import { DashboardV2Sections } from './DashboardV2Sections'
import { DashboardV2Toolbar } from './DashboardV2Toolbar'

export function DashboardV2View(): JSX.Element {
    const { spec, sections, loadFailure, dashboardLoading } = useValues(dashboardV2Logic)
    const { renameDashboard, describeDashboard } = useActions(dashboardV2Logic)
    const { uid } = useMountedLogic(dashboardV2Logic).props

    if (loadFailure === 'not_found') {
        return <NotFound object="dashboard" />
    }
    return (
        <SceneContent>
            <DashboardV2SceneMenuBar />
            <SceneTitleSection
                name={spec?.title}
                description={spec ? (spec.description ?? '') : null}
                resourceType={{ type: 'dashboard' }}
                isLoading={!spec && dashboardLoading}
                canEdit={!!spec}
                onNameChange={renameDashboard}
                onDescriptionChange={describeDashboard}
                saveOnBlur
                renameDebounceMs={0}
            />
            <BindLogic logic={panelEditorLogic} props={{ uid }}>
                <DisplayProvider display={displayOf(spec)}>
                    <div data-quill className="flex flex-col gap-3">
                        {loadFailure === 'error' ? (
                            <DashboardV2LoadError />
                        ) : !spec ? (
                            <Skeleton className="h-64 w-full" data-attr="dashboard-v2-skeleton" />
                        ) : (
                            <>
                                <DashboardV2Toolbar />
                                {sections.length ? (
                                    <DashboardV2EditablePanelsContext.Provider value>
                                        <DashboardV2Sections />
                                    </DashboardV2EditablePanelsContext.Provider>
                                ) : (
                                    <DashboardV2EmptyState />
                                )}
                                <DashboardV2PanelEditor />
                            </>
                        )}
                        <DashboardV2JsonDialog />
                        <DashboardV2DeleteDialog />
                    </div>
                </DisplayProvider>
            </BindLogic>
        </SceneContent>
    )
}
