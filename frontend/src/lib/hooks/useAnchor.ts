import { useEffect } from 'react'

export function useAnchor(hash: string): void {
    useEffect(() => {
        if (hash && document.getElementById(hash.substr(1))) {
            // Check if there is a hash and if an element with that id exists
            const element = document.getElementById(hash.substr(1))

            if (!element) {
                return
            }

            element.classList.add('highlighted')

            // allow time for layout and repainting
            window.requestAnimationFrame(() => {
                element.scrollIntoView({ block: 'start', inline: 'nearest', behavior: 'smooth' })
            })
        }
    }, [hash])
}
