import React from 'react'
import { useValues } from 'kea'

import { useAnchor } from 'lib/hooks/useAnchor'
import { router } from 'kea-router'
import { hot } from 'react-hot-loader/root'

export const Setup = hot(_Setup)
function _Setup() {
    const { location } = useValues(router)

    useAnchor(location.hash)

    return (
        <div>
            <h1 className="page-header">Organization Settings</h1>
        </div>
    )
}
