import React, { ReactElement, RefObject, useEffect, useRef } from 'react'
import { Select } from 'antd'
import { SelectProps } from 'antd/lib/select'
import './SelectGradientOverflow.scss'
import { CloseButton } from './CloseButton'

interface DropdownGradientRendererProps {
    updateScrollGradient: () => void
    innerRef: RefObject<HTMLDivElement>
    menu: ReactElement
}

function DropdownGradientRenderer({
    updateScrollGradient,
    innerRef,
    menu,
}: DropdownGradientRendererProps): JSX.Element {
    useEffect(() => {
        updateScrollGradient()
    })
    return <div ref={innerRef}>{menu}</div>
}

/**
 * Ant Design does not export the component used in multi-select lists,
 * so we're recreating it with a title property for better UX
 */
type CustomTagProps = Parameters<Exclude<SelectProps<any>['tagRender'], undefined>>[0]

function CustomTag({ label, onClose, value }: CustomTagProps): JSX.Element {
    return (
        <div className="ant-select-selection-overflow-item">
            <span className="ant-select-selection-item">
                <span className="ant-select-selection-item-content" title={value.toString()}>
                    {label}
                </span>
                <span className="ant-select-selection-item-remove" unselectable="on" aria-hidden="true">
                    <CloseButton onClick={onClose} style={{ cursor: 'pointer', float: 'none', color: 'inherit' }} />
                </span>
            </span>
        </div>
    )
}

/**
 * Ant Design Select extended with a gradient overlay to indicate a scrollable list.
 */
export function SelectGradientOverflow(props: SelectProps<any>): JSX.Element {
    const dropdownRef = useRef<HTMLDivElement>(null)

    function updateScrollGradient(): void {
        const dropdown = dropdownRef.current
        if (!dropdown) {
            return
        }
        const holder: HTMLDivElement | null = dropdown.querySelector('.rc-virtual-list-holder')
        if (!holder) {
            return
        }
        if (holder.scrollTop > 0) {
            dropdown.classList.add('scrollable-above')
        } else {
            dropdown.classList.remove('scrollable-above')
        }
        if (holder.scrollHeight > holder.scrollTop + holder.offsetHeight) {
            holder.classList.add('scrollable-below')
        } else {
            holder.classList.remove('scrollable-below')
        }
    }

    return (
        <Select
            {...props}
            onPopupScroll={() => {
                updateScrollGradient()
            }}
            tagRender={CustomTag}
            dropdownRender={(menu) => (
                <DropdownGradientRenderer
                    menu={menu}
                    innerRef={dropdownRef}
                    updateScrollGradient={updateScrollGradient}
                />
            )}
        >
            {props.children}
        </Select>
    )
}
