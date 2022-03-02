import React from 'react'
import './ProjectHomepage.scss'
import { PageHeader } from 'lib/components/PageHeader'
import { Dashboard } from 'scenes/dashboard/Dashboard'
import { useValues } from 'kea'
import { teamLogic } from 'scenes/teamLogic'

export function ProjectHomepage(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)

    return (
        <div className="project-homepage">
            <PageHeader title={currentTeam?.name || ''} />
            <Dashboard id={currentTeam?.primary_dashboard} />
        </div>
    )
}
