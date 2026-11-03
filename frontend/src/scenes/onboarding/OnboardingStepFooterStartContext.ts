import { createContext } from 'react'

/** Content a flow shell places at the start of every step's action row, left of the step's own buttons. */
export const OnboardingStepFooterStartContext = createContext<React.ReactNode>(null)
