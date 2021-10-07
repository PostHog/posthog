import React from 'react'
import { PageHeader } from 'lib/components/PageHeader'

export function ErrorProjectUnavailable(): JSX.Element {
    return (
        <div>
            <PageHeader title="Project Unavailable" />
            <p>It seems you don't have access to this project. Switch to a different one.</p>
        </div>
    )
}
