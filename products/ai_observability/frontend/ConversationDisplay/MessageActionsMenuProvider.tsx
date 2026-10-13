import { ReactNode, createContext, useContext, useRef, useState } from 'react'

interface MessageActionsMenuContextValue {
    activeMenuKey: string | null
    setActiveMenuKey: (menuKey: string) => void
}

const MessageActionsMenuContext = createContext<MessageActionsMenuContextValue | null>(null)

export function useMessageActionsMenuContext(): MessageActionsMenuContextValue | null {
    return useContext(MessageActionsMenuContext)
}

export function MessageActionsMenuProvider({
    resetKey,
    children,
}: {
    /** Identity of the displayed conversation. When it changes, the active menu key is cleared. */
    resetKey?: string
    children: ReactNode
}): JSX.Element {
    const [activeMenuKey, setActiveMenuKey] = useState<string | null>(null)
    const previousResetKeyRef = useRef(resetKey)

    // Clear during render, not in an effect, so a key left over from the previous
    // conversation can never reach a newly mounted menu and auto-open it.
    if (previousResetKeyRef.current !== resetKey) {
        previousResetKeyRef.current = resetKey
        setActiveMenuKey(null)
    }

    return (
        <MessageActionsMenuContext.Provider value={{ activeMenuKey, setActiveMenuKey }}>
            {children}
        </MessageActionsMenuContext.Provider>
    )
}
