import React from 'react'
import { useValues } from 'kea'

import { useAnchor } from 'lib/hooks/useAnchor'
import { router } from 'kea-router'
import { userLogic } from 'scenes/userLogic'
import { PageHeader } from 'lib/components/PageHeader'

export function Setup() {
    const { location } = useValues(router)
    const { user } = useValues(userLogic)

    useAnchor(location.hash)

    return (
        <div>
            <PageHeader title={`Organization Settings - ${user.organization.name}`} />
        </div>
    )
}
