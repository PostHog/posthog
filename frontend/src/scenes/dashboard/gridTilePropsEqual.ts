import { objectsEqual } from 'lib/utils/objects'

export function gridTilePropsEqual(prevProps: Record<string, any>, nextProps: Record<string, any>): boolean {
    return [...new Set([...Object.keys(prevProps), ...Object.keys(nextProps)])].every(
        (key) =>
            key === 'children' ||
            (key === 'style'
                ? objectsEqual(prevProps.style, nextProps.style)
                : Object.is(prevProps[key], nextProps[key]))
    )
}
