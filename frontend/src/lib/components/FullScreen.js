import { useEffect } from 'react'

export function FullScreen({ onExit }) {
    const selector = 'aside.ant-layout-sider, .layout-top-content'
    useEffect(() => {
        const myClasses = window.document.querySelectorAll(selector)

        for (let i = 0; i < myClasses.length; i++) {
            myClasses[i].style.display = 'none'
        }

        const handler = () => {
            if (window.document.fullscreenElement === null) {
                onExit && onExit()
            }
        }

        try {
            window.document.body.requestFullscreen().then(() => {
                window.addEventListener('fullscreenchange', handler, false)
            })
        } catch {
            // will break on IE11
        }

        try {
            window.dispatchEvent(new window.Event('scroll'))
            window.dispatchEvent(new window.Event('resize'))
        } catch {
            // will break on IE11
        }

        return () => {
            const myClasses = window.document.querySelectorAll(selector)

            for (let i = 0; i < myClasses.length; i++) {
                myClasses[i].style.display = 'block'
            }
            try {
                window.removeEventListener('fullscreenchange', handler, false)
                if (window.document.fullscreenElement !== null) {
                    window.document.exitFullscreen()
                }
            } catch {
                // will break on IE11
            }

            try {
                window.dispatchEvent(new window.Event('scroll'))
                window.dispatchEvent(new window.Event('resize'))
            } catch {
                // will break on IE11
            }
        }
    }, [])

    return null
}
