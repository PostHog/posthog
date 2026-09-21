import { render, screen } from '@testing-library/react'
import { ReactNode } from 'react'

import { NodeKind } from '~/queries/schema/schema-general'
import type { EventsNode } from '~/queries/schema/schema-general'

import { TrendsDefinitionFields } from './AlertDefinitionFields'

const trendSeriesLabelCases: [string, EventsNode, string][] = [
    ['an all-events series', { kind: NodeKind.EventsNode, event: null }, 'A - All events'],
    [
        'a renamed series',
        { kind: NodeKind.EventsNode, event: '$pageview', custom_name: 'Viewed pricing' },
        'A - Viewed pricing',
    ],
]

jest.mock('kea-forms', () => ({
    ...jest.requireActual('kea-forms'),
    Group: ({ children }: { children: ReactNode }) => <>{children}</>,
}))

jest.mock('@posthog/lemon-ui', () => ({
    ...jest.requireActual('@posthog/lemon-ui'),
    LemonSelect: ({ options }: { options: { label: string; value: number }[] }) => (
        <select>
            {options.map((option) => (
                <option key={option.value}>{option.label}</option>
            ))}
        </select>
    ),
}))

jest.mock('lib/lemon-ui/LemonField', () => ({
    LemonField: ({ children }: { children: ReactNode }) => <>{children}</>,
}))

describe('TrendsDefinitionFields', () => {
    it.each(trendSeriesLabelCases)('labels %s in the alert picker', (_, series, expectedLabel) => {
        render(
            <TrendsDefinitionFields
                alertSeries={[series]}
                formulaNodes={undefined}
                isBreakdownValid={false}
                alertMode="threshold"
            />
        )

        expect(screen.getByText(expectedLabel)).toBeTruthy()
    })
})
