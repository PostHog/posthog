export interface TerminalConfirmation {
    title: string
    description: string
    items: string[]
}

export type ConfirmTerminalOperation = (confirmation: TerminalConfirmation) => Promise<boolean>
