import { useEffect } from 'react'

export function FullScreen({ onExit }: { onExit?: () => any }): null {
    const selector = 'aside.ant-layout-sider, .layout-top-content'
    useEffect(
        () => {
            const myClasses = window.document.querySelectorAll(selector) as NodeListOf<HTMLElement>

            for (let i = 0; i < myClasses.length; i++) {
                myClasses[i].style.display = 'none'
            }

            const handler = (): void => {
                if (window.document.fullscreenElement === null) {
                    onExit?.()
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
                const elements = window.document.querySelectorAll(selector) as NodeListOf<HTMLElement>

                for (let i = 0; i < elements.length; i++) {
                    elements[i].style.display = 'block'
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
        },
        // eslint-disable-next-line react-hooks/exhaustive-deps
        []
    )

    return null
}
