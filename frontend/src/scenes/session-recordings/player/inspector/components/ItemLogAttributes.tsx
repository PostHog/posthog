import { LemonTable } from '@posthog/lemon-ui'

import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'

export interface ItemLogAttributesProps {
    attributes: Record<string, unknown> | null | undefined
    title: string
}

export function ItemLogAttributes({ attributes, title }: ItemLogAttributesProps): JSX.Element | null {
    const rows =
        attributes && typeof attributes === 'object'
            ? Object.entries(attributes).map(([key, value]) => ({
                  key,
                  value: typeof value === 'string' ? value : JSON.stringify(value),
              }))
            : []

    if (rows.length === 0) {
        return null
    }

    return (
        <div className="bg-primary overflow-hidden rounded border border-border">
            <div className="px-3 py-2 bg-bg-light border-b border-border">
                <span className="text-xs font-semibold text-muted uppercase">{title}</span>
            </div>
            <LemonTable
                embedded
                showHeader={false}
                size="small"
                rowKey="key"
                dataSource={rows}
                columns={[
                    {
                        key: 'key',
                        dataIndex: 'key',
                        width: 0,
                        render: (_, record) => (
                            <span className="font-mono text-xs text-muted whitespace-nowrap">{record.key}</span>
                        ),
                    },
                    {
                        key: 'value',
                        dataIndex: 'value',
                        render: (_, record) =>
                            record.value === '' ? (
                                <span className="font-mono text-xs text-muted italic">(empty)</span>
                            ) : (
                                <CopyToClipboardInline
                                    explicitValue={record.value}
                                    description="attribute value"
                                    iconSize="xsmall"
                                    iconPosition="start"
                                    selectable
                                    className="gap-1 font-mono text-xs break-all !whitespace-normal"
                                >
                                    {record.value}
                                </CopyToClipboardInline>
                            ),
                    },
                ]}
            />
        </div>
    )
}
