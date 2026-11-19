import { createContext, useContext, type ReactNode } from 'react'

import { IconCheck, IconChevronDown, IconDashboard } from '@posthog/icons'
import { Button, DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@posthog/quill'
import type { ChartTheme } from '@posthog/quill-charts'

import { useChartTheme } from 'lib/charts/hooks'

import type { Display } from '../spec'

const DisplayContext = createContext<Display>('dense')

export const useDisplay = (): Display => useContext(DisplayContext)

export const displayOf = (spec: { display?: unknown } | null | undefined): Display =>
    spec?.display === 'spacious' ? 'spacious' : 'dense'

export function DisplayProvider({ display, children }: { display: Display; children: ReactNode }): JSX.Element {
    return <DisplayContext.Provider value={display}>{children}</DisplayContext.Provider>
}

export const DISPLAYS: { value: Display; label: string; goodFor: string }[] = [
    {
        value: 'spacious',
        label: 'Spacious',
        goodFor: 'Product, web and marketing analytics, and dashboards you share with the team.',
    },
    {
        value: 'dense',
        label: 'Dense',
        goodFor: 'Monitoring services, on-call, logs and traces, and dashboards you tune by hand.',
    },
]

export function DisplayMenu({
    value,
    onChange,
}: {
    value: Display
    onChange: (display: Display) => void
}): JSX.Element {
    const current = DISPLAYS.find((d) => d.value === value)
    return (
        <DropdownMenu>
            <DropdownMenuTrigger
                render={
                    <Button
                        variant="outline"
                        tooltip="How this dashboard looks. The data stays the same."
                        data-attr="dashboard-v2-display-menu"
                    />
                }
            >
                <IconDashboard /> {current?.label} <IconChevronDown />
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
                {DISPLAYS.map((d) => (
                    <DropdownMenuItem
                        key={d.value}
                        onClick={() => onChange(d.value)}
                        description={d.goodFor}
                        data-attr={`dashboard-v2-display-${d.value}`}
                    >
                        <IconCheck className={value === d.value ? undefined : 'invisible'} /> {d.label}
                    </DropdownMenuItem>
                ))}
            </DropdownMenuContent>
        </DropdownMenu>
    )
}

const SPACIOUS_THEME: Partial<ChartTheme> = {
    gridDashPattern: [2, 4],
    axisLineColor: 'transparent',
}

export const useDisplayChartTheme = (): ChartTheme =>
    useChartTheme(useDisplay() === 'spacious' ? SPACIOUS_THEME : undefined)
