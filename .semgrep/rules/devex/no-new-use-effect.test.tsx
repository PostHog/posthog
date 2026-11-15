// @ts-nocheck
import React, { useEffect as useReactEffect, useLayoutEffect, useEffect, useInsertionEffect } from 'react'

import { useDelayedOnMountEffect, useOnMountEffect } from 'lib/hooks/useOnMountEffect'

function Effects({ id }: { id: string }): JSX.Element {
    // ruleid: no-new-use-effect
    useEffect(() => {
        loadThing(id)
    }, [id])

    // ruleid: no-new-use-effect
    useLayoutEffect(() => measure(), [])

    // ruleid: no-new-use-effect
    useInsertionEffect(() => injectStyle(), [])

    // ruleid: no-new-use-effect
    React.useEffect(() => subscribe(), [])

    // ruleid: no-new-use-effect
    React.useLayoutEffect(() => measure(), [])

    // ruleid: no-new-use-effect
    useReactEffect(() => subscribe(), [])

    // ruleid: no-new-use-effect
    useOnMountEffect(() => loadThing(id))

    // ruleid: no-new-use-effect
    useDelayedOnMountEffect(() => loadThing(id), 1000)

    // nosemgrep: no-new-use-effect -- syncs the third-party map widget, which has no event API
    useEffect(() => mapWidget.setCenter(id), [id])

    // ok: no-new-use-effect
    const { loadThing } = useActions(thingLogic({ id }))

    // ok: no-new-use-effect
    useMountedLogic(thingLogic({ id }))

    // ok: no-new-use-effect
    useEventListener('keydown', onKeyDown)

    // ok: no-new-use-effect
    useResizeObserver({ ref })

    return <div onClick={() => loadThing(id)} />
}
