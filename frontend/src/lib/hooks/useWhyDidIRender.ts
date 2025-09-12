import { useMemo, useRef } from 'react'

import { useFeatureFlag } from './useFeatureFlag'

export function useWhyDidIRender(name: string, props: Record<string, any>): void {
    const oldProps = useRef<Record<string, any>>()
    const logRenderInfo = useFeatureFlag('DEBUG_REACT_RENDERS')

    useMemo(() => {
        if (!logRenderInfo) {
            return
        }

        if (oldProps.current) {
            const oldChangedProps = Object.keys(oldProps.current).filter((key) => !(key in props))
            const changedProps = Object.keys(props).filter((key) => props[key] !== oldProps.current?.[key])

            if (changedProps.length > 0) {
                // oxlint-disable-next-line no-console
                console.log(`${name} props changed:`, [...oldChangedProps, ...changedProps])
            }
        }
        oldProps.current = props
    }, [Object.values(props), name]) // oxlint-disable-line react-hooks/exhaustive-deps
}
