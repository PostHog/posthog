import { LemonSelect } from '@posthog/lemon-ui'

import type { BookActivityMatrixGrouping } from '~/queries/schema/schema-general'

export function DotMatrixProductGroups({
    groupings,
    onSelect,
}: {
    groupings: BookActivityMatrixGrouping[]
    onSelect: (series: string[]) => void
}): JSX.Element {
    return (
        <LemonSelect<string>
            placeholder="Select a product group"
            aria-label="Select a product group"
            data-attr="account-dot-matrix-product-group"
            options={groupings.map((grouping) => ({
                title: grouping.label,
                options: grouping.groups.map((group) => ({
                    value: `${grouping.key}:${group.key}`,
                    label: group.label,
                })),
            }))}
            onChange={(key) => {
                const group = groupings
                    .flatMap((grouping) =>
                        grouping.groups.map((group) => ({ ...group, id: `${grouping.key}:${group.key}` }))
                    )
                    .find((group) => group.id === key)
                if (group) {
                    onSelect([...new Set(group.items)])
                }
            }}
        />
    )
}
