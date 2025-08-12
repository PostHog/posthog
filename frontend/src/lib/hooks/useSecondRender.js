import { useEffect, useState } from 'react'

export function useSecondRender(callback) {
    const [secondRender, setSecondRender] = useState(false)

    useEffect(() => {
        requestAnimationFrame(() => {
            setSecondRender(true)
            callback()
        })
    }, []) // oxlint-disable-line react-hooks/exhaustive-deps

    return secondRender
}
