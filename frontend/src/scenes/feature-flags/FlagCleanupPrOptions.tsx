import { LemonCheckbox, LemonInputSelect } from '@posthog/lemon-ui'

export interface FlagCleanupPrTarget {
    repository: string | null
    source: string
    candidates: string[]
}

export interface FlagCleanupPrOptionsProps {
    flagKey: string
    target: FlagCleanupPrTarget | null
    checked: boolean
    onCheckedChange: (checked: boolean) => void
    repository: string | null
    onRepositoryChange: (repository: string | null) => void
    /** Prefix for the `data-attr` values, e.g. `experiment` gives `experiment-open-cleanup-pr`. */
    dataAttrPrefix: string
    /** Takes precedence over the missing-integration reason, e.g. while the target is still loading. */
    disabledReason?: string
    /** Rendered under the repository picker, which only shows when several repositories are connected. */
    pickerFooter?: JSX.Element | null
    /** Rendered while the checkbox is checked. */
    children?: JSX.Element | null
}

export function FlagCleanupPrOptions({
    flagKey,
    target,
    checked,
    onCheckedChange,
    repository,
    onRepositoryChange,
    dataAttrPrefix,
    disabledReason,
    pickerFooter,
    children,
}: FlagCleanupPrOptionsProps): JSX.Element {
    const needsRepositoryPick = target?.source === 'ambiguous'

    return (
        <div className="space-y-2">
            <LemonCheckbox
                checked={checked}
                onChange={onCheckedChange}
                data-attr={`${dataAttrPrefix}-open-cleanup-pr`}
                disabledReason={
                    disabledReason ??
                    (target?.source === 'no_integration'
                        ? 'Connect GitHub in your project settings to open cleanup PRs'
                        : undefined)
                }
                label={
                    <span>
                        Open a draft PR removing <code>{flagKey}</code> from your code
                    </span>
                }
            />
            {checked && target?.repository && (
                <div className="text-xs text-muted">
                    The PR will be opened in <code>{target.repository}</code>.
                </div>
            )}
            {checked && needsRepositoryPick && (
                <>
                    <LemonInputSelect
                        mode="single"
                        value={repository ? [repository] : []}
                        onChange={(repositories) => onRepositoryChange(repositories[0] ?? null)}
                        options={target.candidates.map((candidate) => ({ key: candidate, label: candidate }))}
                        placeholder="Select a repository"
                        data-attr={`${dataAttrPrefix}-cleanup-repository`}
                    />
                    {pickerFooter}
                </>
            )}
            {checked && children}
        </div>
    )
}
