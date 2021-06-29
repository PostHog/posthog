import React from 'react'
import clsx from 'clsx'

// Imitates how Antd renders the expand icon
// https://github.com/ant-design/ant-design/blob/master/components/table/ExpandIcon.tsx

interface ExpandIconProps {
    prefixCls: string
    onExpand: (record: any, e: React.MouseEvent<HTMLElement>) => void
    record: any
    expanded: boolean
    expandable: boolean
    children?: JSX.Element
}

function ExpandIcon({ prefixCls, onExpand, record, expanded, expandable, children }: ExpandIconProps): JSX.Element {
    console.log('Record', record)
    const iconPrefix = `${prefixCls}-row-expand-icon`
    return (
        <div
            onClick={(e) => {
                onExpand(record, e!)
                e.stopPropagation()
            }}
        >
            <button
                type="button"
                className={clsx(iconPrefix, {
                    [`${iconPrefix}-spaced`]: !expandable,
                    [`${iconPrefix}-expanded`]: expandable && expanded,
                    [`${iconPrefix}-collapsed`]: expandable && !expanded,
                })}
                aria-label={expanded ? 'Collapse row' : 'Expand row'}
            />
            {children}
        </div>
    )
}

export default ExpandIcon
