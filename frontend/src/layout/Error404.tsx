import React from 'react'
import { PageHeader } from 'lib/components/PageHeader'

export function Error404(): JSX.Element {
    return (
        <PageHeader
            title="Page not found"
            caption="The page you were looking for is not here. Please use the navigation and try again."
        />
    )
}
