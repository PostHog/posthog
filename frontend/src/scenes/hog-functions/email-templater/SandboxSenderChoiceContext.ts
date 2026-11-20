import { createContext } from 'react'

export interface SandboxSenderChoice {
    selected: boolean
    /** True while the project has no verified sender, so the test sender is the only one that can send. */
    onlySender: boolean
    fromLine: string | null
    onSelect: () => void
}

export const SandboxSenderChoiceContext = createContext<SandboxSenderChoice | null>(null)
