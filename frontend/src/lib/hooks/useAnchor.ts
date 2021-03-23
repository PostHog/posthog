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
            const elementPosition = element.getBoundingClientRect().top + window.pageYOffset
            window.scrollTo({
                top: elementPosition - 50 - 32, // compensate for header & top margin of pages
                behavior: 'smooth',
            })
        }
    }, [hash]) // Fires every time hash changes
}
