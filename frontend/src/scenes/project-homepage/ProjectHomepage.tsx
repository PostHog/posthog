import React from 'react'
import './ProjectHomepage.scss'
import { PageHeader } from 'lib/components/PageHeader'
import { Dashboard } from 'scenes/dashboard/Dashboard'
import { useValues } from 'kea'
import { teamLogic } from 'scenes/teamLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { DashboardLocation } from '~/types'

export function ProjectHomepage(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)

    return (
        <div className="project-homepage">
            <PageHeader title={currentTeam?.name || ''} />
            {currentTeam?.primary_dashboard ? (
                <Dashboard id={currentTeam.primary_dashboard} location={DashboardLocation.ProjectHomepage} />
            ) : (
                <div>
                    <h1>Set the default dashboard for this project</h1>
                </div>
            )}
        </div>
    )
}

export const scene: SceneExport = {
    component: ProjectHomepage,
}
