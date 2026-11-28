import { useContext } from 'react'

import {
    Badge,
    Progress,
    Table,
    TableBody,
    TableCell,
    TableHead,
    TableHeader,
    TableRow,
    Tabs,
    TabsContent,
    TabsList,
    TabsTrigger,
} from '@posthog/quill'

import { FiltersContext } from '../../filters/filtersContext'

const BREAKDOWNS = [
    {
        key: 'sources',
        label: 'Sources',
        rows: [
            { name: 'Google', visitors: 4210 },
            { name: 'Direct', visitors: 2860 },
            { name: 'Newsletter', visitors: 940 },
            { name: 'Hacker News', visitors: 520 },
        ],
    },
    {
        key: 'devices',
        label: 'Devices',
        rows: [
            { name: 'Desktop', visitors: 5630 },
            { name: 'Mobile', visitors: 2510 },
            { name: 'Tablet', visitors: 390 },
        ],
    },
    {
        key: 'countries',
        label: 'Countries',
        rows: [
            { name: 'United States', visitors: 3120 },
            { name: 'Germany', visitors: 1480 },
            { name: 'Brazil', visitors: 1150 },
            { name: 'India', visitors: 990 },
        ],
    },
]

// TODO(2026-11-26): Delete with the kitchen sink fixture, once a product renders its own custom content in a dashboard.
export function TabbedBreakdown(): JSX.Element {
    const { filters } = useContext(FiltersContext)
    return (
        <Tabs defaultValue={BREAKDOWNS[0].key} className="flex h-full min-h-0 flex-col">
            <div className="flex items-center justify-between gap-2">
                <TabsList variant="line">
                    {BREAKDOWNS.map(({ key, label }) => (
                        <TabsTrigger key={key} value={key} data-attr="dashboard-v2-example-breakdown-tab">
                            {label}
                        </TabsTrigger>
                    ))}
                </TabsList>
                {filters.length > 0 && (
                    <Badge variant="info">
                        {filters.length} {filters.length === 1 ? 'filter' : 'filters'} applied
                    </Badge>
                )}
            </div>
            {BREAKDOWNS.map(({ key, rows }) => {
                const total = rows.reduce((sum, row) => sum + row.visitors, 0)
                return (
                    <TabsContent key={key} value={key} className="min-h-0 overflow-auto">
                        <Table size="sm" fullWidth>
                            <TableHeader>
                                <TableRow>
                                    <TableHead>Name</TableHead>
                                    <TableHead expand>Share</TableHead>
                                    <TableHead align="right">Visitors</TableHead>
                                </TableRow>
                            </TableHeader>
                            <TableBody>
                                {rows.map(({ name, visitors }) => (
                                    <TableRow key={name}>
                                        <TableCell>{name}</TableCell>
                                        <TableCell expand>
                                            <Progress value={(visitors / total) * 100} />
                                        </TableCell>
                                        <TableCell align="right" className="tabular-nums">
                                            {visitors.toLocaleString()}
                                        </TableCell>
                                    </TableRow>
                                ))}
                            </TableBody>
                        </Table>
                    </TabsContent>
                )
            })}
        </Tabs>
    )
}
