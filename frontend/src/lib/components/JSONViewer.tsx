import './JSONViewer.scss'

import ReactJson, { ReactJsonViewProps } from '@microlink/react-json-view'
import { useValues } from 'kea'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'

export enum JSONViewerTheme {
    DARK = 'railscasts',
    LIGHT = 'rjv-default',
}

export function JSONViewer({
    name = null, // Don't label the root node as "root" by default
    displayDataTypes = false, // Reduce visual clutter
    displayObjectSize = false, // Reduce visual clutter
    ...props
}: ReactJsonViewProps): JSX.Element {
    const { isDarkModeOn } = useValues(themeLogic)

    return (
        <ReactJson // eslint-disable-line react/forbid-elements
            // HACK: Weirdly when `theme` prop changes on the same component instance, the JSON viewer drops `style`
            // we provided, so we force a different identity between dark and light mode with `key`, to re-render fully
            key={isDarkModeOn ? 'dark' : 'light'}
            style={{ background: 'transparent', overflowWrap: 'anywhere' }} // More aggressive wrapping against overflow
            theme={isDarkModeOn ? 'railscasts' : 'rjv-default'}
            name={name}
            displayDataTypes={displayDataTypes}
            displayObjectSize={displayObjectSize}
            enableClipboard={(copy) => {
                // The library wraps string values in quotes.
                // Re-copy with raw string value so users get the actual content.
                const text = typeof copy.src === 'string' ? copy.src : JSON.stringify(copy.src, null, 2)
                navigator.clipboard.writeText(text).catch((e) => console.warn('Failed to copy to clipboard', e))
            }}
            {...props}
        />
    )
}
