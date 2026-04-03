import { BindLogic, useActions, useValues } from 'kea'
import { useEffect, useRef } from 'react'

import { ScrollableShadows } from 'lib/components/ScrollableShadows/ScrollableShadows'
import { uuid } from 'lib/utils'
import { ThreadAutoScroller } from 'scenes/max/components/ThreadAutoScroller'
import { maxLogic } from 'scenes/max/maxLogic'
import { MaxThreadLogicProps, maxThreadLogic } from 'scenes/max/maxThreadLogic'
import { Thread } from 'scenes/max/Thread'

import { aiFirstHomepageLogic } from './aiFirstHomepageLogic'
import { HOMEPAGE_TAB_ID } from './constants'

export function HomepageThread(): JSX.Element {
    const { query } = useValues(aiFirstHomepageLogic)
    const { threadLogicKey, conversation } = useValues(maxLogic({ tabId: HOMEPAGE_TAB_ID }))
    const { askMax, setQuestion } = useActions(maxLogic({ tabId: HOMEPAGE_TAB_ID }))

    const scrollRef = useRef<HTMLDivElement | null>(null)

    // Mark the scroll container so ThreadAutoScroller can find it
    useEffect(() => {
        scrollRef.current?.setAttribute('data-attr', 'max-scrollable')
    }, [])

    // Send the initial query once on mount
    const hasSentInitial = useRef(false)

    useEffect(() => {
        if (query && !hasSentInitial.current) {
            hasSentInitial.current = true
            setQuestion(query)
            setTimeout(() => {
                askMax(query)
            }, 100)
        }
    }, []) // eslint-disable-line react-hooks/exhaustive-deps

    const threadProps: MaxThreadLogicProps = {
        tabId: HOMEPAGE_TAB_ID,
        conversationId: threadLogicKey || uuid(),
        conversation,
    }

    return (
        <BindLogic logic={maxLogic} props={{ tabId: HOMEPAGE_TAB_ID }}>
            <BindLogic logic={maxThreadLogic} props={threadProps}>
                <ScrollableShadows direction="vertical" styledScrollbars className="grow min-h-0" scrollRef={scrollRef}>
                    <ThreadAutoScroller>
                        <Thread className="p-3" />
                    </ThreadAutoScroller>
                </ScrollableShadows>
            </BindLogic>
        </BindLogic>
    )
}
