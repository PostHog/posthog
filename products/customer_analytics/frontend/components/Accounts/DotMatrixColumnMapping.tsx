import { useId } from 'react'

import { LemonLabel, LemonSelect } from '@posthog/lemon-ui'

import type { DotMatrixSourceMapping } from './dotMatrixTileConfig'

const FIELDS = [
    { key: 'row', label: 'Row', required: true },
    { key: 'column', label: 'Column', required: true },
    { key: 'series', label: 'Series', required: false },
    { key: 'value', label: 'Value', required: false },
    { key: 'user', label: 'User', required: false },
] as const

const EMPTY_LABELS = { series: 'Single series', value: 'Count rows', user: 'No user column' }

export function DotMatrixColumnMapping({
    columns,
    mapping,
    onChange,
}: {
    columns: string[]
    mapping: DotMatrixSourceMapping
    onChange: (mapping: DotMatrixSourceMapping) => void
}): JSX.Element {
    const id = useId()
    return (
        <div className="flex flex-col gap-2">
            <div className="flex flex-wrap gap-3">
                {FIELDS.map(({ key, label, required }) => (
                    <div key={key} className="flex flex-col gap-1 min-w-32 flex-1">
                        <LemonLabel htmlFor={`${id}-${key}`}>{label}</LemonLabel>
                        <LemonSelect
                            id={`${id}-${key}`}
                            value={mapping[key] ?? ''}
                            data-attr={`dot-matrix-mapping-${key}`}
                            placeholder={`Choose ${label.toLowerCase()}`}
                            options={[
                                ...(!required
                                    ? [
                                          {
                                              value: '',
                                              label:
                                                  key === 'value' && mapping.user ? 'Count people' : EMPTY_LABELS[key],
                                          },
                                      ]
                                    : []),
                                ...columns.map((column) => ({ value: column, label: column })),
                            ]}
                            onChange={(value) => {
                                const next = { ...mapping }
                                if (value || required) {
                                    next[key] = value
                                } else {
                                    delete next[key]
                                }
                                onChange(next)
                            }}
                            fullWidth
                        />
                    </div>
                ))}
            </div>
            <p className="text-xs text-secondary mb-0">
                Map a user column to count each person once when several series are selected.
            </p>
        </div>
    )
}
