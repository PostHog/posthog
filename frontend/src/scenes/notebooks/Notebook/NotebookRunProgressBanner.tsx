import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { Spinner } from 'lib/lemon-ui/Spinner'

// Shown above the document while a whole-notebook run is going. Accent styling, like the
// downstream-cells nudge on a cell: this reports progress rather than a problem. Each cell
// still shows its own running state, so this only answers "how far along is the run".
export function NotebookRunProgressBanner({ label, onStop }: { label: string; onStop: () => void }): JSX.Element {
    return (
        <div className="mt-2 flex flex-wrap items-center gap-2 rounded border border-accent bg-accent-highlight-secondary p-2 text-xs">
            <Spinner textColored />
            <span className="grow truncate">{label}</span>
            <LemonButton type="secondary" size="xsmall" onClick={onStop}>
                Stop
            </LemonButton>
        </div>
    )
}
