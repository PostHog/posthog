import { useEffect } from 'react'

export function useAnchor(hash) {
    useEffect(() => {
        if (hash && document.getElementById(hash.substr(1))) {
            // Check if there is a hash and if an element with that id exists
            const element = document.getElementById(hash.substr(1))
            element.style.background = 'rgba(247, 165, 1, 0.3)'
            var elementPosition = element.getBoundingClientRect().top + window.pageYOffset
            window.scrollTo({
                top: elementPosition - 80, // compensate for header
                behavior: 'smooth',
            })
        }
    }, [hash]) // Fires every time hash changes
}
