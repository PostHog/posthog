import { RefObject, useEffect, useState } from 'react'

// adapted from https://github.com/streamich/react-use/blob/master/src/useHoverDirty.ts
export function useIsHovering(ref: RefObject<Element>): boolean {
    const [value, setValue] = useState(false)

    useEffect(() => {
        const el = ref.current
        if (!el) {
            return
        }

        const onMouseOver = (): void => setValue(true)
        const onMouseOut = (): void => setValue(false)

        el.addEventListener('mouseover', onMouseOver)
        el.addEventListener('mouseout', onMouseOut)

        return () => {
            el.removeEventListener('mouseover', onMouseOver)
            el.removeEventListener('mouseout', onMouseOut)
        }
    }, [ref])

    return value
}

export default useIsHovering
