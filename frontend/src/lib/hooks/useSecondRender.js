import { useEffect, useState } from 'react'

export function useSecondRender(callback) {
    const [secondRender, setSecondRender] = useState(false)

    useEffect(() => {
        requestAnimationFrame(() => {
            setSecondRender(true)
            callback()
        })
    }, [])

    return secondRender
}
