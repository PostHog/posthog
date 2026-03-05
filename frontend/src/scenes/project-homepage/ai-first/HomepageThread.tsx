import { BindLogic, useActions, useValues } from 'kea'
import { useEffect, useRef } from 'react'

import { ScrollableShadows } from 'lib/components/ScrollableShadows/ScrollableShadows'
import { uuid } from 'lib/utils'
import { ChatToolbar } from 'scenes/max/components/AiFirstMaxInstance'
import { ThreadAutoScroller } from 'scenes/max/components/ThreadAutoScroller'
import { maxLogic } from 'scenes/max/maxLogic'
import { MaxThreadLogicProps, maxThreadLogic } from 'scenes/max/maxThreadLogic'
import { Thread } from 'scenes/max/Thread'

import { aiFirstHomepageLogic } from './aiFirstHomepageLogic'

export const HOMEPAGE_TAB_ID = 'homepage-ai'

export function HomepageThread(): JSX.Element {
    const { query } = useValues(aiFirstHomepageLogic)
    const { threadLogicKey, conversation, conversationId } = useValues(maxLogic({ tabId: HOMEPAGE_TAB_ID }))
    const { askMax, setQuestion } = useActions(maxLogic({ tabId: HOMEPAGE_TAB_ID }))

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
                <ChatToolbar conversationId={conversationId} />
                <ScrollableShadows direction="vertical" styledScrollbars className="grow min-h-0">
                    <ThreadAutoScroller>
                        <Thread className="p-3" />
                    </ThreadAutoScroller>
                </ScrollableShadows>
            </BindLogic>
        </BindLogic>
    )
}
