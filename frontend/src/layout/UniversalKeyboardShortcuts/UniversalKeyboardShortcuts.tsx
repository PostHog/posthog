import { useMountedLogic } from "kea"
import { universalKeyboardShortcutsLogic } from "./universalKeyboardShortcutsLogic"

export const UniversalKeyboardShortcuts = ({ children }: { children: React.ReactNode }) => {
    useMountedLogic(universalKeyboardShortcutsLogic)

    return children
}