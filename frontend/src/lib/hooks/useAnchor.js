import { useEffect } from 'react'

export function useAnchor(hash) {
    useEffect(() => {
        if (hash && document.getElementById(hash.substr(1))) {
            // Check if there is a hash and if an element with that id exists
            document.getElementById(hash.substr(1)).scrollIntoView({ behavior: 'smooth' })
        }
    }, [hash]) // Fires every time hash changes
}
