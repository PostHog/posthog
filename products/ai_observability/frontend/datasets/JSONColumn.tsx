import { useValues } from 'kea'
import React from 'react'

import { Tooltip } from '@posthog/lemon-ui'

import { HighlightedJSONViewer } from 'lib/components/HighlightedJSONViewer'
import { JSONViewerTheme } from 'lib/components/JSONViewer'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'

const MemoizedJSONViewer = React.memo(({ json }: { json: unknown }) => {
    const { isDarkModeOn } = useValues(themeLogic)
    const source = typeof json === 'object' && json !== null ? json : { value: json }

    return (
        <HighlightedJSONViewer
            src={source}
            // Swap the theme because Tooltip inverses colors
            theme={isDarkModeOn ? JSONViewerTheme.LIGHT : JSONViewerTheme.DARK}
        />
    )
})

export interface JSONColumnProps {
    children?: unknown
}

export const JSONColumn = ({ children }: JSONColumnProps): JSX.Element => {
    if (children === null || children === undefined) {
        return <span>—</span>
    }

    return (
        <Tooltip
            placement="bottom"
            title={<MemoizedJSONViewer json={children} />}
            className="overflow-auto"
            containerClassName="max-w-xl"
        >
            <pre className="line-clamp-1 p-0 m-0 max-w-48 text-ellipsis">{JSON.stringify(children)}</pre>
        </Tooltip>
    )
}
