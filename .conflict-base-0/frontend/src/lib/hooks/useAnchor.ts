import { useEffect } from 'react'

export function useAnchor(hash: string): void {
    useEffect(() => {
        if (hash && document.getElementById(hash.slice(1))) {
            // Allow time for layout and repainting
            // (setTimeout because requestAnimationFrame resulted in final scroll position being slightly off)
            setTimeout(() => {
                // Check if there is a hash and if an element with that id exists
                const element = document.getElementById(hash.slice(1))
                if (!element) {
                    return
                }
                element.classList.add('animate-mark')
                element.scrollIntoView()
            }, 1000 / 60)
        }
    }, [hash])
}
