import { LemonButton } from 'lib/lemon-ui/LemonButton'

import type { DotMatrixAxisItem } from '../types'
import { DOT_MATRIX_MOCK_ACCOUNTS, DOT_MATRIX_MOCK_GROUPS, DOT_MATRIX_MOCK_PRODUCTS } from './dotMatrixMockFixtures'
import { type DotMatrixMockPerson } from './dotMatrixMockTypes'

interface DotMatrixDemoRowHeaderProps {
    row: DotMatrixAxisItem
    colorMode: 'family' | 'product'
    rowPeople: DotMatrixMockPerson[]
    accountMeta?: string
    openAccount: (id: string) => void
}

export function DotMatrixDemoRowHeader({
    row,
    colorMode,
    rowPeople,
    accountMeta,
    openAccount,
}: DotMatrixDemoRowHeaderProps): JSX.Element {
    const account = DOT_MATRIX_MOCK_ACCOUNTS.find((item) => item.id === row.key)
    if (account) {
        return (
            <div className="DotMatrixDemo__account-label">
                <svg width="24" height="24" viewBox="0 0 24 24" aria-hidden="true">
                    <rect width="24" height="24" rx="5" fill={account.logo} />
                    <text
                        x="12"
                        y="12"
                        dominantBaseline="central"
                        textAnchor="middle"
                        fill="#ffffff"
                        fontSize="12"
                        fontWeight="700"
                    >
                        {account.name[0]}
                    </text>
                </svg>
                <div className="DotMatrixDemo__label-copy">
                    <LemonButton
                        type="tertiary"
                        size="xsmall"
                        className="DotMatrixDemo__account-name"
                        onClick={() => openAccount(account.id)}
                        data-attr="dot-matrix-open-account"
                    >
                        {account.name}
                    </LemonButton>
                    <span>{accountMeta}</span>
                </div>
            </div>
        )
    }
    if (row.group === 'family') {
        return <span className="DotMatrixDemo__family-label">{row.label}</span>
    }
    const productKey = row.key.split('/')[1]
    const index = DOT_MATRIX_MOCK_PRODUCTS.findIndex(([key]) => key === productKey)
    if (index >= 0) {
        const persons = rowPeople
        return (
            <div className="DotMatrixDemo__product-label">
                <span>
                    <svg width="8" height="8" aria-hidden="true">
                        <circle
                            cx="4"
                            cy="4"
                            r="4"
                            fill={
                                colorMode === 'product'
                                    ? DOT_MATRIX_MOCK_PRODUCTS[index][2]
                                    : DOT_MATRIX_MOCK_GROUPS[Math.floor(index / 6)].color
                            }
                        />
                    </svg>
                    <span>{row.label}</span>
                </span>
                <small>{`${persons.length} users`}</small>
            </div>
        )
    }
    return <span>{row.label ?? row.key}</span>
}
