/** Shared by the two arms of the Replay Vision option: the card and the checkbox. */
export interface ReplayVisionScannerOptionProps {
    checked: boolean
    onChange: (checked: boolean) => void
    disabledReason?: string
    sessionPrice: string
}
