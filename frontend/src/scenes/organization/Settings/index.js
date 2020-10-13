import React from 'react'
import { useValues } from 'kea'

import { useAnchor } from 'lib/hooks/useAnchor'
import { router } from 'kea-router'
import { hot } from 'react-hot-loader/root'
import { userLogic } from 'scenes/userLogic'

export const Setup = hot(_Setup)
function _Setup() {
    const { location } = useValues(router)
    const { user } = useValues(userLogic)

    useAnchor(location.hash)

    return (
        <div>
            <h1 className="page-header">Organization Settings – {user.organization.name}</h1>
        </div>
    )
}
