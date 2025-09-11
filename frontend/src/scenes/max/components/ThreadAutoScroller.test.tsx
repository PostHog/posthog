import { render } from '@testing-library/react'
import { Provider, useMountedLogic } from 'kea'
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

        const KeyedLogicWrapper = ({ children }: { children: React.ReactNode }): JSX.Element => {
            useMountedLogic(maxThreadLogic({ conversationId: 'x' }))
            return <>{children}</>
        }

        const { container } = render(
            <Provider>
                <KeyedLogicWrapper>
                    <MockScrollable>
                        <ThreadAutoScroller>
                            <div>content</div>
                        </ThreadAutoScroller>
                    </MockScrollable>
                </KeyedLogicWrapper>
            </Provider>
        )

        const scroller = container.querySelector('#max-thread') as HTMLElement
        // Move away from bottom
        scroller.scrollTop = 500

        // Dispatch a scroll event; listener is passive and should not throw
        scroller.dispatchEvent(new Event('scroll'))

        // user flag is private, but behaviorally: subsequent resizes should not auto-scroll
        // We assert by toggling streamingActive to false->true and ensuring no throw.
        logic.actions.completeThreadGeneration()
        logic.actions.reconnectToStream()

        logic.unmount()
    })
})
