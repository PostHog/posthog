import { IconCheck, IconX } from '@posthog/icons'
import {
    Button,
    Dialog,
    DialogBody,
    DialogContent,
    DialogFooter,
    DialogHeader,
    DialogTitle,
    Heading,
    Item,
    ItemContent,
    ItemMedia,
    ItemTitle,
    Table,
    TableBody,
    TableCell,
    TableHead,
    TableHeader,
    TableRow,
    Text,
} from '@posthog/quill'

import { MarketingAnalyticsColumnsSchemaNames } from '~/queries/schema/schema-general'

import { TestMappingResult } from '../../logic/marketingAnalyticsSettingsLogic'

function FieldStatusIcon({ mapped }: { mapped: boolean }): JSX.Element {
    return mapped ? <IconCheck className="text-success-foreground" /> : <IconX className="text-muted-foreground" />
}

function fieldLabel(fieldName: MarketingAnalyticsColumnsSchemaNames): string {
    return fieldName.replace(/_/g, ' ').replace(/\b\w/g, (l) => l.toUpperCase())
}

function FieldRows({
    title,
    fields,
    isFieldMapped,
    renderColumnMappingCombobox,
}: {
    title: string
    fields: MarketingAnalyticsColumnsSchemaNames[]
    isFieldMapped: (fieldName: MarketingAnalyticsColumnsSchemaNames) => boolean
    renderColumnMappingCombobox: (fieldName: MarketingAnalyticsColumnsSchemaNames) => JSX.Element
}): JSX.Element {
    return (
        <div className="flex flex-col gap-2">
            <Heading size="sm" render={<h4 className="m-0" />}>
                {title}
            </Heading>
            {[...fields].sort().map((fieldName) => (
                <div key={fieldName} className="flex flex-wrap items-center gap-3">
                    <span className="flex w-6 justify-center">
                        <FieldStatusIcon mapped={isFieldMapped(fieldName)} />
                    </span>
                    <Text size="xs" weight="medium" render={<span className="w-40" />}>
                        {fieldLabel(fieldName)}
                    </Text>
                    <div className="min-w-48 flex-1">{renderColumnMappingCombobox(fieldName)}</div>
                </div>
            ))}
        </div>
    )
}

export function QuillColumnMappingModal({
    tableName,
    isOpen,
    onClose,
    requiredFields,
    optionalFields,
    requiredFieldsConfigured,
    testResult,
    editDisabledReason,
    isFieldMapped,
    renderColumnMappingCombobox,
    onClearAllMappings,
    onTestMapping,
}: {
    tableName: string
    isOpen: boolean
    onClose: () => void
    requiredFields: MarketingAnalyticsColumnsSchemaNames[]
    optionalFields: MarketingAnalyticsColumnsSchemaNames[]
    requiredFieldsConfigured: number
    testResult: TestMappingResult | undefined
    editDisabledReason: string | null | undefined
    isFieldMapped: (fieldName: MarketingAnalyticsColumnsSchemaNames) => boolean
    renderColumnMappingCombobox: (fieldName: MarketingAnalyticsColumnsSchemaNames) => JSX.Element
    onClearAllMappings: () => void
    onTestMapping: () => void
}): JSX.Element {
    const showTestResult = testResult && testResult.status !== 'idle' && testResult.status !== 'loading'
    const showSampleData =
        testResult?.status === 'success' &&
        testResult.columns &&
        testResult.sample_data &&
        testResult.sample_data.length > 0

    return (
        <Dialog open={isOpen} onOpenChange={(open) => !open && onClose()}>
            <DialogContent>
                <DialogHeader>
                    <DialogTitle>{`Configure ${tableName} mapping`}</DialogTitle>
                </DialogHeader>
                <DialogBody>
                    <div className="flex flex-col gap-6">
                        <FieldRows
                            title="Required fields"
                            fields={requiredFields}
                            isFieldMapped={isFieldMapped}
                            renderColumnMappingCombobox={renderColumnMappingCombobox}
                        />

                        {optionalFields.length > 0 && (
                            <FieldRows
                                title="Optional fields"
                                fields={optionalFields}
                                isFieldMapped={isFieldMapped}
                                renderColumnMappingCombobox={renderColumnMappingCombobox}
                            />
                        )}

                        <div className="flex flex-wrap items-center gap-2">
                            <Button
                                variant="outline"
                                onClick={onTestMapping}
                                loading={testResult?.status === 'loading'}
                                tooltip="Test the mapping by running the adapter query"
                                disabledReason={
                                    editDisabledReason ??
                                    (requiredFieldsConfigured < requiredFields.length
                                        ? 'Configure all required fields first'
                                        : undefined)
                                }
                            >
                                Test mapping
                            </Button>
                            <Button
                                variant="outline"
                                onClick={onClearAllMappings}
                                tooltip="Clear all mappings for this table"
                            >
                                Clear
                            </Button>
                        </div>

                        {showTestResult && (
                            <Item tone={testResult.status === 'success' ? 'success' : 'destructive'} size="sm">
                                <ItemMedia>{testResult.status === 'success' ? <IconCheck /> : <IconX />}</ItemMedia>
                                <ItemContent>
                                    <ItemTitle>
                                        {testResult.status === 'success'
                                            ? `Test passed - ${testResult.message}`
                                            : `Test failed - ${testResult.message}`}
                                    </ItemTitle>
                                    {showSampleData && (
                                        <div className="max-h-60 overflow-auto">
                                            <Table>
                                                <TableHeader>
                                                    <TableRow>
                                                        {testResult.columns?.map((col) => (
                                                            <TableHead key={col}>{col}</TableHead>
                                                        ))}
                                                    </TableRow>
                                                </TableHeader>
                                                <TableBody>
                                                    {testResult.sample_data?.map((row, rowIdx) => (
                                                        <TableRow key={rowIdx}>
                                                            {row.map((cell: any, cellIdx: number) => (
                                                                <TableCell
                                                                    key={cellIdx}
                                                                    className="max-w-48 truncate"
                                                                    title={String(cell ?? '')}
                                                                >
                                                                    {cell === null ? (
                                                                        <Text
                                                                            size="xs"
                                                                            variant="muted"
                                                                            render={<span className="italic" />}
                                                                        >
                                                                            null
                                                                        </Text>
                                                                    ) : (
                                                                        String(cell)
                                                                    )}
                                                                </TableCell>
                                                            ))}
                                                        </TableRow>
                                                    ))}
                                                </TableBody>
                                            </Table>
                                        </div>
                                    )}
                                </ItemContent>
                            </Item>
                        )}
                    </div>
                </DialogBody>
                <DialogFooter className="sm:justify-between">
                    <Text size="xs" variant="muted" render={<span />}>
                        {`${requiredFieldsConfigured}/${requiredFields.length} required fields configured`}
                    </Text>
                    <Button variant="primary" onClick={onClose}>
                        Done
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    )
}
