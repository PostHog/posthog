import { Link } from '@posthog/lemon-ui'

import { CohortUsedInSection } from './cohortUsedIn'

export function CohortUsedInList({ sections }: { sections: CohortUsedInSection[] }): JSX.Element {
    return (
        <div className="flex flex-col gap-y-2">
            {sections.map(({ title, total, items }) => (
                <div key={title}>
                    <h5 className="text-xs font-semibold uppercase opacity-60 mb-0">
                        {title}
                        {total > items.length && ` (${items.length} of ${total} shown)`}
                    </h5>
                    <ul className="list-disc pl-4 mb-0">
                        {items.map(({ key, url, label }) => (
                            <li key={key}>
                                <Link to={url}>{label}</Link>
                            </li>
                        ))}
                    </ul>
                </div>
            ))}
        </div>
    )
}
