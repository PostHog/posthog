import React, { ReactElement, RefObject, useEffect, useRef } from 'react'
import { Select, Tag, Tooltip } from 'antd'
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
 * Ant Design Tag with custom styling in .scss to match default style
 */
type CustomTagProps = Parameters<Exclude<SelectProps<any>['tagRender'], undefined>>[0]

function CustomTag({ label, onClose, value }: CustomTagProps): JSX.Element {
    return (
        <Tooltip title={value.toString()}>
            <Tag>
                <span className="label">{label}</span>
                <CloseButton onClick={onClose} />
            </Tag>
        </Tooltip>
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
