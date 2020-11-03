import React, { useState } from 'react'
import { DownOutlined } from '@ant-design/icons'
import { Button } from 'antd'

export function Dropdown({ className, style, 'data-attr': dataAttr, buttonStyle, children, title, titleEmpty }) {
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
            className={className}
            style={{
                display: 'inline',
                marginTop: -6,
                ...style,
            }}
            data-attr={dataAttr}
        >
            <Button style={{ ...buttonStyle }} onClick={open}>
                {isEmpty && titleEmpty ? titleEmpty : title}
                {!isEmpty && <DownOutlined className="text-muted" style={{ marginRight: '-6px' }} />}
            </Button>
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
