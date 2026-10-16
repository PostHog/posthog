import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'

import { detailItems, offlineDetailItemResults } from './offlineDetailFixtures'
import { OfflineResultTag } from './OfflineResultTag'

describe('OfflineResultTag', () => {
    afterEach(cleanup)

    it.each([
        [0.9999999, 'gte', '0.9999999', 'Fail'],
        [1.0000001, 'lte', '1.0000001', 'Fail'],
        [1.23456789, 'gte', '1.23457', 'Pass'],
    ] as const)('shows an accurate verdict and exact tooltip for %s with %s', (value, operator, label, verdict) => {
        const result = offlineDetailItemResults(detailItems[0].id)[0]
        render(
            <OfflineResultTag
                result={{ ...result, status: 'ok', value }}
                scorer={{ ...result.scorer, kind: 'numeric', config: { passing_rule: { operator, threshold: 1 } } }}
            />
        )
        expect(screen.getByText(label)).toBeInTheDocument()
        expect(screen.getByTitle(`${verdict}: ${value}`)).toHaveClass(
            `LemonTag--${verdict === 'Pass' ? 'success' : 'danger'}`
        )
    })

    it.each([
        ['ok', 'Fail: Detected', 'Detected', 'danger'],
        ['error', 'Error', 'Error', 'danger'],
        ['skipped', 'Skipped', 'Skipped', 'muted'],
        ['not_applicable', 'Not applicable', 'Not applicable', 'muted'],
    ] as const)('keeps a %s result distinct from the boolean verdict', (status, title, label, type) => {
        const result = offlineDetailItemResults(detailItems[0].id)[0]
        render(
            <OfflineResultTag
                result={{ ...result, status, value: true }}
                scorer={{
                    ...result.scorer,
                    kind: 'boolean',
                    config: { true_label: 'Detected', true_is_failure: true },
                }}
            />
        )
        expect(screen.getByText(label)).toBeInTheDocument()
        expect(screen.getByTitle(title)).toHaveClass(`LemonTag--${type}`)
    })
})
