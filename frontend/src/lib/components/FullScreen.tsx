import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'

export function FullScreen({ onExit }: { onExit?: () => any }): null {
    const selector = '.layout-top-content'
    useOnMountEffect(() => {
        const myClasses = window.document.querySelectorAll<HTMLElement>(selector)

        for (let i = 0; i < myClasses.length; i++) {
            myClasses[i].style.display = 'none'
        }

        const handler = (): void => {
            if (window.document.fullscreenElement === null) {
                onExit?.()
            }
        }

        try {
            void document.body.requestFullscreen().then(() => {
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
            const elements = window.document.querySelectorAll<HTMLElement>(selector)

            for (let i = 0; i < elements.length; i++) {
                elements[i].style.display = 'block'
            }
            try {
                window.removeEventListener('fullscreenchange', handler, false)
                if (document.fullscreenElement !== null) {
                    void document.exitFullscreen()
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
    })

    return null
}
