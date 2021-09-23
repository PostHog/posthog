import React from 'react'
import { PageHeader } from 'lib/components/PageHeader'

export function Error404(): JSX.Element {
    return (
        <div>
            <PageHeader title="Page Not Found" />
            <p>The page you were looking for is not here. Please use the navigation and try again.</p>
        </div>
    )
}
