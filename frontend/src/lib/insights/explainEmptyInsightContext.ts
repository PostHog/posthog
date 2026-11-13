import { createContext, useContext } from 'react'

// Off unless the insight page turns it on, so a dashboard of empty tiles never looks up why each is empty.
export const ExplainEmptyInsightContext = createContext(false)

export function useExplainEmptyInsight(): boolean {
    return useContext(ExplainEmptyInsightContext)
}
