import posthog from 'posthog-js'
import { ReactNode, useState } from 'react'

import { IconExpand45 } from '@posthog/icons'
import { LemonButton, LemonModal } from '@posthog/lemon-ui'

import { copyToClipboard } from 'lib/utils/copyToClipboard'

export function TableCellValue({
    title,
    value,
    children,
}: {
    title: string
    value: string | object
    children: ReactNode
}): JSX.Element {
    const [expandedValue, setExpandedValue] = useState<string | null>(null)

    return (
        <div className="group relative min-w-0">
            {children}
            <span className="absolute top-0 right-0 opacity-0 group-hover:opacity-100 focus-within:opacity-100">
                <LemonButton
                    className="bg-surface-primary"
                    size="xsmall"
                    noPadding
                    icon={<IconExpand45 />}
                    aria-label={`View full value of ${title}`}
                    tooltip="View full value"
                    onClick={(event) => {
                        event.stopPropagation()
                        setExpandedValue(typeof value === 'string' ? value : JSON.stringify(value, null, 2))
                        posthog.capture('sql table cell expanded', { value_type: typeof value })
                    }}
                />
            </span>
            <LemonModal
                isOpen={expandedValue !== null}
                onClose={() => setExpandedValue(null)}
                title={title}
                width={720}
                footer={
                    <LemonButton
                        type="primary"
                        onClick={() => {
                            if (expandedValue !== null) {
                                void copyToClipboard(expandedValue, 'cell value')
                            }
                        }}
                    >
                        Copy value
                    </LemonButton>
                }
            >
                <pre className="ph-no-capture m-0 max-h-[60vh] overflow-auto whitespace-pre-wrap [overflow-wrap:anywhere]">
                    {expandedValue}
                </pre>
            </LemonModal>
        </div>
    )
}
