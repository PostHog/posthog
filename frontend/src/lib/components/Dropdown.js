import React, { useState } from 'react'
import { DownOutlined } from '@ant-design/icons'

export function Dropdown({
    className,
    style,
    'data-attr': dataAttr,
    buttonStyle,
    children,
    buttonClassName,
    title,
    titleEmpty,
}) {
    const [menuOpen, setMenuOpen] = useState(false)

    const isEmpty = !(children && (!Array.isArray(children) || children.length))

    function close(e) {
        if (e.target.closest('.dropdown-no-close') || e.target.closest('.react-datepicker')) return
        setMenuOpen(false)
        document.removeEventListener('click', close)
    }

    function open(e) {
        e.preventDefault()
        setMenuOpen(true)
        document.addEventListener('click', close)
    }

    return (
        <div
            className={'dropdown ' + className}
            style={{
                display: 'inline',
                marginTop: -6,
                ...style,
            }}
            data-attr={dataAttr}
        >
            <a className={'cursor-pointer ' + buttonClassName} style={{ ...buttonStyle }} onClick={open} href="#">
                {isEmpty && titleEmpty ? titleEmpty : title}
                {!isEmpty && <DownOutlined style={{ marginLeft: '3px', color: 'rgba(0, 0, 0, 0.25)' }} />}
            </a>
            {!isEmpty && (
                <div
                    className={'dropdown-menu ' + (menuOpen && 'show')}
                    style={{
                        borderRadius: 2,
                    }}
                    aria-labelledby="dropdownMenuButton"
                >
                    {children}
                </div>
            )}
        </div>
    )
}
