import { useEffect, useState } from 'react'

/** Whether the page shows the dark theme, read from `body[theme]`, the attribute the surrounding CSS
 *  follows. `themeLogic.isDarkModeOn` can lag behind it, which left the editor light on a dark page. */
export function useBodyIsDark(): boolean {
    const [isDark, setIsDark] = useState(() => document.body.getAttribute('theme') === 'dark')
    useEffect(() => {
        const sync = (): void => setIsDark(document.body.getAttribute('theme') === 'dark')
        // The attribute may already have changed between the first render and here.
        sync()
        const observer = new MutationObserver(sync)
        observer.observe(document.body, { attributeFilter: ['theme'] })
        return () => observer.disconnect()
    }, [])
    return isDark
}
