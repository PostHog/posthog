import clsx from 'clsx'

import { IconCheck } from '@posthog/icons'

import { LemonTag } from 'lib/lemon-ui/LemonTag'
import { Link } from 'lib/lemon-ui/Link'

type WidgetTypePickerCardProps = {
    label: string
    description: string
    selected: boolean
    preview: JSX.Element
    onSelect: () => void
    /** Highlight the widget as new when its product hasn't been adopted by the team yet. */
    isNew?: boolean
    /** Product name shown in the learn-more banner (e.g. "Error tracking"). */
    productName?: string
    /** Docs link surfaced in the learn-more banner; when set the banner is shown. */
    learnMoreHref?: string
    onLearnMore?: () => void
}

function WidgetTypePickerSelectionIndicator({ selected }: { selected: boolean }): JSX.Element {
    return (
        <span
            className={clsx(
                'flex shrink-0 items-center justify-center rounded-full size-5 transition-colors',
                selected ? 'bg-accent text-primary-inverse' : 'border-2 border-primary bg-bg-light'
            )}
            aria-hidden
        >
            {selected ? <IconCheck className="size-3" /> : null}
        </span>
    )
}

export function WidgetTypePickerCard({
    label,
    description,
    selected,
    preview,
    onSelect,
    isNew,
    productName,
    learnMoreHref,
    onLearnMore,
}: WidgetTypePickerCardProps): JSX.Element {
    return (
        <div
            role="checkbox"
            aria-checked={selected}
            aria-label={label}
            tabIndex={0}
            className={clsx(
                'text-left w-full rounded border p-3 transition-colors cursor-pointer',
                'focus:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2',
                selected ? 'border-accent bg-accent/5 ring-1 ring-accent' : 'border-primary hover:border-accent/40'
            )}
            onClick={onSelect}
            onKeyDown={(e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault()
                    onSelect()
                }
            }}
        >
            <div className="flex items-center justify-between gap-2">
                <div className="flex items-center gap-1.5 min-w-0">
                    <span className="font-semibold truncate">{label}</span>
                    {isNew ? (
                        <LemonTag type="highlight" size="small" className="shrink-0">
                            New
                        </LemonTag>
                    ) : null}
                </div>
                <WidgetTypePickerSelectionIndicator selected={selected} />
            </div>
            <p className="text-xs text-muted m-0 mt-0.5 mb-2">{description}</p>
            {isNew && learnMoreHref ? (
                <div className="flex items-center gap-2 rounded bg-accent-highlight-secondary px-2 py-1 mb-2 text-xs">
                    <span className="text-secondary">
                        {productName ? `${productName} is new for your team.` : 'New for your team.'}
                    </span>
                    <Link
                        to={learnMoreHref}
                        target="_blank"
                        onClick={(e) => {
                            e.stopPropagation()
                            onLearnMore?.()
                        }}
                    >
                        Learn more
                    </Link>
                </div>
            ) : null}
            <div className="pointer-events-none select-none overflow-hidden rounded" aria-hidden="true">
                {preview}
            </div>
        </div>
    )
}
