import { IconPlus } from '@posthog/icons'

export function ScratchTemplateCard({ onSelect }: { onSelect: () => void }): JSX.Element {
    return (
        <div className="relative flex h-full gap-3 p-3 rounded-lg border border-primary bg-surface-primary hover:border-accent transition-colors motion-reduce:transition-none">
            <div className="flex items-center justify-center size-10 shrink-0 rounded-lg bg-fill-secondary text-secondary">
                <IconPlus className="size-5 shrink-0" />
            </div>
            <div className="flex flex-col flex-1 min-w-0 gap-0.5">
                <h3 className="m-0 text-sm font-semibold truncate">
                    {/* The pseudo-element stretches this button over the whole card, so the card is one click target. */}
                    <button
                        type="button"
                        className="text-left cursor-pointer after:absolute after:inset-0 after:rounded-lg focus-visible:outline-none focus-visible:after:ring-2 focus-visible:after:ring-inset focus-visible:after:ring-accent"
                        data-attr="evaluation-template-scratch"
                        onClick={onSelect}
                    >
                        Start from scratch
                    </button>
                </h3>
                <p className="m-0 text-xs text-secondary">Write your own prompt or code</p>
            </div>
        </div>
    )
}
