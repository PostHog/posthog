import { createContext, useContext } from 'react'

import { SessionRecordingPlayerLogicProps } from '../sessionRecordingPlayerLogic'

export interface PlayerSidebarContextValue {
    logicProps: SessionRecordingPlayerLogicProps
    seekToTime: (timeMs: number) => void
}

const PlayerSidebarContext = createContext<PlayerSidebarContextValue | null>(null)

export function PlayerSidebarContextProvider({
    children,
    logicProps,
    seekToTime,
}: {
    children: React.ReactNode
    logicProps: SessionRecordingPlayerLogicProps
    seekToTime: (timeMs: number) => void
}): JSX.Element {
    return <PlayerSidebarContext.Provider value={{ logicProps, seekToTime }}>{children}</PlayerSidebarContext.Provider>
}

export function usePlayerSidebarContext(): PlayerSidebarContextValue {
    const context = useContext(PlayerSidebarContext)
    if (!context) {
        throw new Error('usePlayerSidebarContext must be used within a PlayerSidebarContextProvider')
    }
    return context
}
