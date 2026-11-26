import { Badge, Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@posthog/quill'

import { DnsRecord } from '../../scenes/settings/emailSettingsHelpers'

export function QuillDnsRecordsTable({ records }: { records: DnsRecord[] }): JSX.Element | null {
    if (!records || records.length === 0) {
        return null
    }

    return (
        <Table>
            <TableHeader>
                <TableRow>
                    <TableHead>Type</TableHead>
                    <TableHead>Name</TableHead>
                    <TableHead>Value</TableHead>
                    <TableHead>Status</TableHead>
                </TableRow>
            </TableHeader>
            <TableBody>
                {records.map((record: DnsRecord, i: number) => (
                    <TableRow key={i}>
                        <TableCell className="font-mono">{record.record_type}</TableCell>
                        <TableCell className="max-w-50 break-all whitespace-normal font-mono">{record.name}</TableCell>
                        <TableCell className="max-w-75 break-all whitespace-normal font-mono">{record.value}</TableCell>
                        <TableCell>
                            {record.valid === 'valid' ? (
                                <Badge variant="success">Valid</Badge>
                            ) : (
                                <Badge variant="warning">Pending</Badge>
                            )}
                        </TableCell>
                    </TableRow>
                ))}
            </TableBody>
        </Table>
    )
}
