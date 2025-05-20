import { batchChanges, BuiltLogic, getContext, LogicWrapper } from 'kea'
import { useActions } from 'kea'
import { useValues } from 'kea'
import React, { useEffect } from 'react'

import { maxLogic } from './maxLogic'
import { maxThreadLogic, MaxThreadLogicProps } from './maxThreadLogic'
import { maxThreadRegistryLogic } from './maxThreadRegistryLogic'

/**
 * Max's Thread logic provider. Keeps track of the logics that are currently streaming, so we don't lose
 * the progress. When the component unmounts, it cleans up the logics that are no longer streaming.
 */
export function MaxBindThreadLogic({ children }: { children: React.ReactNode }): JSX.Element {
    const { threadLogicKey, conversation } = useValues(maxLogic)
    const { mountedThreadLogics } = useValues(maxThreadRegistryLogic)
    const { cleanMountedThreadLogics, registerThreadLogic } = useActions(maxThreadRegistryLogic)

    const threadProps: MaxThreadLogicProps = {
        conversationId: threadLogicKey,
        conversation,
    }
    const threadLogic = maxThreadLogic(threadProps)

    // Check if the thread logic is not already mounted and stored in the cache
    if (!mountedThreadLogics[threadLogic.pathString]) {
        batchChanges(() => {
            threadLogic.mount()
            registerThreadLogic(threadLogic)
        })
    }

    useEffect(() => {
        // When the current thread unmounts, clean up the logics that aren't streaming
        return () => {
            cleanMountedThreadLogics()
        }
    }, [cleanMountedThreadLogics, threadLogic.pathString])

    // Store the maxThreadLogic in the context similarly to how BindLogic does it
    const LogicContext = getOrCreateContextForLogicWrapper(maxThreadLogic)

    return <LogicContext.Provider value={threadLogic}>{children}</LogicContext.Provider>
}

/**
 * Taken from https://github.com/keajs/kea/blob/master/src/react/bind.tsx#L12
 */
function getOrCreateContextForLogicWrapper(logic: LogicWrapper): React.Context<BuiltLogic | undefined> {
    let context = getContext().react.contexts.get(logic)
    if (!context) {
        context = React.createContext(undefined as BuiltLogic | undefined)
        getContext().react.contexts.set(logic, context)
    }
    return context
}
