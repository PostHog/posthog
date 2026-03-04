import { BindLogic, useActions, useValues } from 'kea'
import { useEffect, useRef } from 'react'

import { uuid } from 'lib/utils'
import { ThreadAutoScroller } from 'scenes/max/components/ThreadAutoScroller'
import { maxLogic } from 'scenes/max/maxLogic'
import { MaxThreadLogicProps, maxThreadLogic } from 'scenes/max/maxThreadLogic'
import { Thread } from 'scenes/max/Thread'

import { aiFirstHomepageLogic } from './aiFirstHomepageLogic'

const HOMEPAGE_TAB_ID = 'homepage-ai'

export function HomepageThread(): JSX.Element {
    const { query } = useValues(aiFirstHomepageLogic)
    const { threadLogicKey, conversation } = useValues(maxLogic({ tabId: HOMEPAGE_TAB_ID }))
    const { askMax, setQuestion } = useActions(maxLogic({ tabId: HOMEPAGE_TAB_ID }))

    const hasSubmitted = useRef(false)

    useEffect(() => {
        if (query && !hasSubmitted.current) {
            hasSubmitted.current = true
            setQuestion(query)
            // Small delay to ensure maxThreadLogic is mounted
            setTimeout(() => {
                askMax(query)
            }, 100)
        }
    }, [query, setQuestion, askMax])

    // Reset submission tracking when query changes
    useEffect(() => {
        hasSubmitted.current = false
    }, [query])

    const threadProps: MaxThreadLogicProps = {
        tabId: HOMEPAGE_TAB_ID,
        conversationId: threadLogicKey || uuid(),
        conversation,
    }

    return (
        <BindLogic logic={maxLogic} props={{ tabId: HOMEPAGE_TAB_ID }}>
            <BindLogic logic={maxThreadLogic} props={threadProps}>
                <ThreadAutoScroller>
                    <Thread className="p-3" />
                </ThreadAutoScroller>
            </BindLogic>
        </BindLogic>
    )
}
