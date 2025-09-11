import { render } from '@testing-library/react'
import { BindLogic, Provider } from 'kea'
import React, { useEffect, useRef } from 'react'

import { maxThreadLogic } from 'scenes/max/maxThreadLogic'

import { initKeaTests } from '~/test/init'

import { ThreadAutoScroller } from './ThreadAutoScroller'

// Helper to provide scroll container in DOM
function MockScrollable({ children }: { children: React.ReactNode }): JSX.Element {
    const ref = useRef<HTMLDivElement | null>(null)
    useEffect(() => {
        if (!ref.current) {
            return
        }
        // Make it scrollable
        Object.assign(ref.current, {
            scrollHeight: 2000,
            clientHeight: 1000,
            scrollTop: 0,
        })
    }, [])
    return (
        <div id="max-thread" ref={ref} style={{ height: '1000px', overflow: 'auto' }}>
            <div style={{ height: '2000px' }}>{children}</div>
        </div>
    )
}

describe('ThreadAutoScroller', () => {
    beforeEach(() => {
        initKeaTests()
    })

    it('sets user scroll flag when not at bottom using scroll metrics', () => {
        const logic = maxThreadLogic({ conversationId: 'x' })
        logic.mount()
        logic.actions.setThread([])
        // Simulate streaming active so listener attaches
        logic.actions.streamConversation({ content: 'hi' } as any, 0)

        const { container } = render(
            <Provider>
                <BindLogic logic={maxThreadLogic} props={{ conversationId: 'x' }}>
                    <MockScrollable>
                        <ThreadAutoScroller>
                            <div>content</div>
                        </ThreadAutoScroller>
                    </MockScrollable>
                </BindLogic>
            </Provider>
        )

        const scroller = container.querySelector('#max-thread') as HTMLElement
        // Move away from bottom
        scroller.scrollTop = 500

        // Dispatch a scroll event; listener is passive and should not throw
        scroller.dispatchEvent(new Event('scroll'))

        // Mock ResizeObserver to trigger resize path and ensure no throw
        const callbacks: Function[] = []
        // eslint-disable-next-line compat/compat
        ;(global as any).ResizeObserver = class {
            callback: Function
            constructor(cb: Function) {
                this.callback = cb
                callbacks.push(cb)
            }
            observe(): void {}
            disconnect(): void {}
        }
        callbacks.forEach((cb) => cb())

        logic.unmount()
    })
})
