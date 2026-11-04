import React from 'react'

import { LemonCheckbox, Link } from '@posthog/lemon-ui'

import { LemonBanner } from 'lib/lemon-ui/LemonBanner'

import type { WarehouseMigrationCreatorApi } from 'products/warehouse_sources/frontend/generated/api.schemas'

export interface MigrationPrefillConfirmProps {
    creator: WarehouseMigrationCreatorApi | null
    rows: { label: string; value: string }[]
    confirmed: boolean
    onConfirmedChange: (confirmed: boolean) => void
    noun: 'source' | 'destination'
    trustNote: string
    newSetupUrl: string
    className?: string
}

export function MigrationPrefillConfirm({
    creator,
    rows,
    confirmed,
    onConfirmedChange,
    noun,
    trustNote,
    newSetupUrl,
    className,
}: MigrationPrefillConfirmProps): JSX.Element {
    return (
        <LemonBanner type="warning" className={className}>
            <p className="font-semibold mb-1">Check where your credentials go</p>
            <p className="m-0 mb-2 text-sm">
                {creator
                    ? `${creator.first_name || creator.email} (${creator.email}) prepared this connection.`
                    : 'A migration prepared this connection.'}{' '}
                {trustNote}
            </p>
            <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 m-0 mb-2 text-sm">
                {rows.map(({ label, value }) => (
                    <React.Fragment key={label}>
                        <dt className="text-secondary">{label}</dt>
                        <dd className="m-0 font-mono break-all">{value}</dd>
                    </React.Fragment>
                ))}
            </dl>
            <div className="flex flex-wrap items-center justify-between gap-2">
                <LemonCheckbox
                    checked={confirmed}
                    onChange={onConfirmedChange}
                    label="I confirm this is the right server"
                    // pinned: autocapture data-attr values, renaming breaks dashboards
                    data-attr={`${noun}-connect-confirm-prefill`}
                />
                <Link to={newSetupUrl} data-attr={`${noun}-connect-new-${noun}-instead`}>
                    {`Set up a new ${noun} instead`}
                </Link>
            </div>
        </LemonBanner>
    )
}
