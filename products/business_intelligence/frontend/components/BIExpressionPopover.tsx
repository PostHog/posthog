import { LemonDropdown } from '@posthog/lemon-ui'

import { HogQLEditor } from 'lib/components/HogQLEditor/HogQLEditor'

import { BIDataSource } from '~/queries/schema/schema-business-intelligence'
import { NodeKind } from '~/queries/schema/schema-general'
import { escapeDottedHogQLIdentifier } from '~/queries/utils'

export function BIExpressionPopover({
    visible,
    value,
    source,
    placeholder,
    onChange,
    onClose,
    children,
}: {
    visible: boolean
    value: string
    source: BIDataSource
    placeholder?: string
    onChange: (value: string) => void
    onClose: () => void
    children: React.ReactElement
}): JSX.Element {
    return (
        <LemonDropdown
            visible={visible}
            closeOnClickInside={false}
            // The trigger opens a menu of its own, so only closing is handled here
            onVisibilityChange={(nextVisible) => !nextVisible && onClose()}
            placement="bottom-start"
            overlay={
                <div className="w-120 max-w-[max(60vw,20rem)]">
                    <HogQLEditor
                        value={value}
                        placeholder={placeholder}
                        metadataSource={{
                            kind: NodeKind.HogQLQuery,
                            query: `SELECT * FROM ${escapeDottedHogQLIdentifier(source.table)}`,
                            connectionId: source.connectionId,
                        }}
                        onChange={(nextValue) => {
                            onChange(nextValue)
                            onClose()
                        }}
                    />
                </div>
            }
        >
            {children}
        </LemonDropdown>
    )
}
