import { IconWrench } from '@posthog/icons'
import { LemonSegmentedButton } from '@posthog/lemon-ui'

export type HomeSectionKey = 'to-review' | 'expensive-users' | 'evals' | 'topics'

export interface HomeSectionPlaceholderProps {
    section: HomeSectionKey
    title: string
    switchLabels?: [string, string]
}

export function HomeSectionPlaceholder({ section, title, switchLabels }: HomeSectionPlaceholderProps): JSX.Element {
    return (
        // pinned: data-attrs feed autocapture; dashboards and tests find the section by this value
        <section
            className="flex min-w-0 flex-col gap-3 rounded border bg-surface-primary p-3"
            data-attr={`home-section-${section}`}
        >
            <div className="flex min-h-7 flex-wrap items-center justify-between gap-2">
                <h3 className="m-0 text-sm font-semibold">{title}</h3>
                {switchLabels ? (
                    <LemonSegmentedButton
                        size="xsmall"
                        disabledReason="Not available here yet"
                        value={switchLabels[0]}
                        options={switchLabels.map((label) => ({ value: label, label }))}
                    />
                ) : null}
            </div>
            <div
                className="flex h-40 w-full flex-col items-center justify-center gap-1 rounded border border-dashed text-secondary"
                style={{
                    backgroundImage:
                        'repeating-linear-gradient(135deg, var(--warning-highlight) 0 14px, transparent 14px 28px)',
                }}
            >
                <IconWrench className="text-xl text-warning" />
                <span className="text-sm font-semibold">Under construction</span>
            </div>
        </section>
    )
}
