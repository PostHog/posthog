import { RefObject, useEffect, useState } from 'react'

// adapted from https://github.com/streamich/react-use/blob/master/src/useHoverDirty.ts
const useIsHovering = (ref: RefObject<Element>): boolean => {
    if (typeof ref !== 'object' || typeof ref.current === 'undefined') {
        console.error('useHoverDirty expects a single ref argument.')
    }

    const [value, setValue] = useState(false)

    useEffect(() => {
        const onMouseOver = (): void => setValue(true)
        const onMouseOut = (): void => setValue(false)

        if (ref && ref.current) {
            ref.current.addEventListener('mouseover', onMouseOver)
            ref.current.addEventListener('mouseout', onMouseOut)
        }

        // fixes react-hooks/exhaustive-deps warning about stale ref elements
        const { current } = ref

        return () => {
            if (current) {
                current.removeEventListener('mouseover', onMouseOver)
                current.removeEventListener('mouseout', onMouseOut)
            }
        }
    }, [ref])

    return value
}

export default useIsHovering
