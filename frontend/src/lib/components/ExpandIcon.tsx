import clsx from 'clsx'

// Imitates how Antd renders the expand icon
// https://github.com/ant-design/ant-design/blob/master/components/table/ExpandIcon.tsx

export interface ExpandIconProps {
    prefixCls: string
    onExpand: (record: any, e: React.MouseEvent<HTMLElement>) => void
    record: any
    expanded: boolean
    expandable: boolean
    children?: JSX.Element
}

export function ExpandIcon({
    prefixCls,
    onExpand,
    record,
    expanded,
    expandable,
    children,
}: ExpandIconProps): JSX.Element {
    const iconPrefix = `${prefixCls}-row-expand-icon`
    return (
        <div
            className="flex items-center"
            onClick={(e) => {
                onExpand(record, e)
                e.stopPropagation()
            }}
        >
            <button
                type="button"
                className={clsx(iconPrefix, 'mr-2', {
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
