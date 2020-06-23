import React from 'react'
import { useValues } from 'kea'

export function RetentionTable({ logic }) {
    const { retention, retentionLoading } = useValues(logic)

    return <pre>{JSON.stringify({ retentionLoading, retention }, null, 2)}</pre>
}
