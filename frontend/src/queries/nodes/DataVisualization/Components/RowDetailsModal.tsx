import clsx from 'clsx'
import { useState } from 'react'

import { IconCode, IconCopy, IconMinus, IconPlus } from '@posthog/icons'
import { LemonButton, LemonModal, LemonTable } from '@posthog/lemon-ui'

import { JSONViewer } from 'lib/components/JSONViewer'
import { copyToClipboard } from 'lib/utils/copyToClipboard'

export interface RowDetailsModalProps {
    isOpen: boolean
    onClose: () => void
    /** Column labels, in display order. */
    columns: string[]
    /** The row's cell values, aligned with `columns`. `null` when no row is selected. */
    values: any[] | null
}

export function RowDetailsModal({ isOpen, onClose, columns, values }: RowDetailsModalProps): JSX.Element {
    const [showRawJson, setShowRawJson] = useState<Record<string, boolean>>({})
    const [wordWrap, setWordWrap] = useState<Record<string, boolean>>({})

    if (!values) {
        return <></>
    }

    const isJsonString = (str: string): boolean => {
        try {
            const parsed = JSON.parse(str)
            return typeof parsed === 'object' && parsed !== null
        } catch {
            return false
        }
    }

    const tableData = columns.map((column, index) => {
        const value = values[index]
        const isStringifiedJson = typeof value === 'string' && isJsonString(value)
        const isJson = typeof value === 'object' || isStringifiedJson
        const jsonValue = isStringifiedJson ? JSON.parse(value) : value
        // One raw text form for both the raw view and the copy button. An object needs stringifying,
        // but a JSON string is already raw text, so stringifying it again would wrap it in quotes and
        // escape every quote inside it.
        const rawValue =
            value === null ? 'null' : typeof value === 'object' ? JSON.stringify(value, null, 2) : String(value)

        return {
            column,
            isJson,
            rawValue,
            value:
                value === null ? (
                    <span className="text-muted">null</span>
                ) : isJson ? (
                    <div className="flex gap-2 w-full">
                        <div className="w-full overflow-hidden">
                            {showRawJson[column] ? (
                                <pre
                                    className={clsx(
                                        'm-0 font-mono',
                                        wordWrap[column]
                                            ? 'whitespace-pre-wrap break-all'
                                            : 'overflow-x-auto hide-scrollbar'
                                    )}
                                >
                                    {rawValue}
                                </pre>
                            ) : (
                                <div className="overflow-x-auto max-w-full">
                                    <JSONViewer src={jsonValue} name={null} collapsed={1} sortKeys={true} />
                                </div>
                            )}
                        </div>
                    </div>
                ) : (
                    <div className="overflow-x-auto">
                        <span className="whitespace-pre-wrap break-all font-mono">{String(value)}</span>
                    </div>
                ),
        }
    })

    return (
        <LemonModal title="Row details" isOpen={isOpen} onClose={onClose} width={800}>
            <div className="RowDetailsModal max-h-[70vh] overflow-y-auto px-2 overflow-x-hidden">
                <LemonTable
                    dataSource={tableData}
                    className="w-full table-fixed"
                    columns={[
                        {
                            title: 'Column',
                            dataIndex: 'column',
                            className: 'font-semibold',
                            width: '35%',
                            render: (_, record) => <span title={record.column}>{record.column}</span>,
                        },
                        {
                            title: 'Value',
                            dataIndex: 'value',
                            className: 'px-4 overflow-hidden',
                            width: '65%',
                            render: (_, record) => (
                                <div className="flex items-center gap-2 w-full">
                                    <div className="flex-1 overflow-x-auto pr-2">{record.value}</div>
                                    <div className="flex flex-row gap-1 flex-shrink-0 ml-auto">
                                        {record.isJson && record.rawValue && record.rawValue != 'null' && (
                                            <LemonButton
                                                size="small"
                                                icon={<IconCode />}
                                                onClick={() =>
                                                    setShowRawJson((prev) => ({
                                                        ...prev,
                                                        [record.column]: !prev[record.column],
                                                    }))
                                                }
                                                tooltip={showRawJson[record.column] ? 'Show formatted' : 'Show raw'}
                                            />
                                        )}
                                        {showRawJson[record.column] && (
                                            <LemonButton
                                                size="small"
                                                icon={wordWrap[record.column] ? <IconMinus /> : <IconPlus />}
                                                onClick={() =>
                                                    setWordWrap((prev) => ({
                                                        ...prev,
                                                        [record.column]: !prev[record.column],
                                                    }))
                                                }
                                                tooltip={wordWrap[record.column] ? 'Collapse' : 'Expand'}
                                            />
                                        )}
                                        <LemonButton
                                            size="small"
                                            icon={<IconCopy />}
                                            onClick={() => void copyToClipboard(record.rawValue, 'value')}
                                            tooltip="Copy value"
                                        />
                                    </div>
                                </div>
                            ),
                        },
                    ]}
                />
            </div>
        </LemonModal>
    )
}
