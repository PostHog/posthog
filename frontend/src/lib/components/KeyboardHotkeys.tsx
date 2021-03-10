import { useEventListener } from 'lib/hooks/useEventListener'
import React from 'react'

interface HotKeyInterface {
    action: () => void
    disabled?: boolean
}

type Keys =
    | 'a'
    | 'b'
    | 'c'
    | 'd'
    | 'e'
    | 'f'
    | 'g'
    | 'h'
    | 'i'
    | 'j'
    | 'k'
    | 'l'
    | 'm'
    | 'n'
    | 'o'
    | 'p'
    | 'q'
    | 'r'
    | 's'
    | 't'
    | 'u'
    | 'v'
    | 'w'
    | 'x'
    | 'y'
    | 'z'

interface HotKeys {
    a?: HotKeyInterface
    b?: HotKeyInterface
    c?: HotKeyInterface
    d?: HotKeyInterface
    e?: HotKeyInterface
    f?: HotKeyInterface
    g?: HotKeyInterface
    h?: HotKeyInterface
    i?: HotKeyInterface
    j?: HotKeyInterface
    k?: HotKeyInterface
    l?: HotKeyInterface
    m?: HotKeyInterface
    n?: HotKeyInterface
    o?: HotKeyInterface
    p?: HotKeyInterface
    q?: HotKeyInterface
    r?: HotKeyInterface
    s?: HotKeyInterface
    t?: HotKeyInterface
    u?: HotKeyInterface
    v?: HotKeyInterface
    w?: HotKeyInterface
    x?: HotKeyInterface
    y?: HotKeyInterface
    z?: HotKeyInterface
}

export function KeyboardHotkeys({ hotkeys }: { hotkeys: HotKeys }): JSX.Element {
    useEventListener('keydown', (event) => {
        const key = (event as KeyboardEvent).key

        // Ignore typing on inputs (default behavior)
        if ((event.target as HTMLElement).tagName === 'INPUT') {
            return
        }

        for (const relevantKey of Object.keys(hotkeys)) {
            const hotkey = hotkeys[relevantKey as Keys]

            if (!hotkey || hotkey.disabled) {
                continue
            }

            if (key.toLowerCase() === relevantKey) {
                hotkey.action()
                break
            }
        }
    })

    return <></>
}
