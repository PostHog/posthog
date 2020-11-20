import React, { useEffect, useRef } from 'react'
import { Select } from 'antd'
import './SelectGradientOverflow.scss'

function DropdownGradientRenderer(props: Record<string, any>): JSX.Element {
    useEffect(() => {
        props.setScrollGradient()
    })

    return <div ref={props.innerRef}>{props.menu}</div>
}

export function SelectGradientOverflow(props: Record<string, any>): JSX.Element {
    /* Extend Ant Select component with a gradient overlay to indicate a scrollable list */
    const dropdownRef = useRef(null as HTMLElement | null)

    const SetScrollGradient = (): void => {
        const target = dropdownRef.current?.querySelector('.rc-virtual-list-holder')

        if (target === null || target === undefined) {
            return
        }

        if (target.scrollTop + target.offsetHeight === target.scrollHeight) {
            target.classList.remove('scroll-gradient')
        } else {
            target.classList.add('scroll-gradient')
        }
    }

    return (
        <Select
            {...props}
            onPopupScroll={() => {
                SetScrollGradient()
            }}
            dropdownRender={(menu) => (
                <DropdownGradientRenderer menu={menu} innerRef={dropdownRef} setScrollGradient={SetScrollGradient} />
            )}
        >
            {props.children}
        </Select>
    )
}
