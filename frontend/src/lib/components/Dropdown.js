import React, { useEffect, useState } from 'react'

export function Dropdown({ className, style, 'data-attr': dataAttr, buttonStyle, children, buttonClassName, title }) {
    const [menuOpen, setMenuOpen] = useState(false)

    function close(e) {
        if (e.target.closest('.dropdown-no-close') || e.target.closest('.react-datepicker')) return
        setMenuOpen(false)
    }

    function open(e) {
        e.preventDefault()
        setMenuOpen(true)
    }

    useEffect(() => {
        document.addEventListener('click', close)
        return () => {
            document.removeEventListener('click', close)
        }
    }, [menuOpen])

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
                {title || <span>&hellip;</span>}
            </a>
            <div
                className={'dropdown-menu ' + (menuOpen && 'show')}
                style={{
                    borderRadius: 2,
                }}
                aria-labelledby="dropdownMenuButton"
            >
                {children}
            </div>
        </div>
    )
}
