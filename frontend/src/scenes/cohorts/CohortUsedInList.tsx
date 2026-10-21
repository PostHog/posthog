import { Link } from '@posthog/lemon-ui'

import { pluralize } from 'lib/utils/strings'

import { CohortUsedInSection } from './cohortUsedIn'

function hiddenUsesNote(hidden: number, noun: string): string {
    return hidden === 1
        ? `You don't have access to 1 ${noun} that uses this cohort. Ask someone who can edit it to remove the cohort.`
        : `You don't have access to ${pluralize(hidden, noun)} that use this cohort. Ask someone who can edit them to remove the cohort.`
}

export function CohortUsedInList({ sections }: { sections: CohortUsedInSection[] }): JSX.Element {
    return (
        <div className="flex flex-col gap-y-2">
            {sections.map(({ title, noun, total, hidden = 0, items }) => (
                <div key={title}>
                    <h5 className="text-xs font-semibold uppercase opacity-60 mb-0">
                        {title}
                        {total - hidden > items.length && (
                            <span>{` (${items.length} of ${total - hidden} shown)`}</span>
                        )}
                    </h5>
                    {items.length > 0 && (
                        <ul className="list-disc pl-4 mb-0">
                            {items.map(({ key, url, label }) => (
                                <li key={key}>
                                    <Link to={url}>{label}</Link>
                                </li>
                            ))}
                        </ul>
                    )}
                    {hidden > 0 && <p className="text-secondary mb-0">{hiddenUsesNote(hidden, noun)}</p>}
                </div>
            ))}
        </div>
    )
}
