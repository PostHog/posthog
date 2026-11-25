import { useModeSelector } from './ModeSelector'
import { QuillModeMenu } from './QuillModeMenu'

/** The legacy chat's agent mode selector in the quill composer: the same choices as the lemon `ModeSelector`. */
export function QuillModeSelector(): JSX.Element {
    return <QuillModeMenu {...useModeSelector()} />
}
