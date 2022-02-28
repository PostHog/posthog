import React from 'react'
import './ProjectHomepage.scss'
import { PageHeader } from 'lib/components/PageHeader'
import { SessionRecordingsTable } from 'scenes/session-recordings/SessionRecordingsTable'
import { RecordingTableLocation } from 'scenes/session-recordings/sessionRecordingsTableLogic'

export function ProjectHomepage(): JSX.Element {
    return (
        <div className="project-homepage">
            <PageHeader title="Homepage" />
            <SessionRecordingsTable
                onlyShowList
                tableLocation={RecordingTableLocation.HomePage}
             />
        </div>
    )
}
