import { createContext } from 'react'

export interface SandboxSenderChoice {
    selected: boolean
    fromLine: string | null
    onSelect: () => void
}

export const SandboxSenderChoiceContext = createContext<SandboxSenderChoice | null>(null)
