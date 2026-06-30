import React from 'react'

export const FramerLogo = React.memo(function FramerLogo(): JSX.Element {
    return (
        <svg
            fill="#000000"
            className="h-8 w-8 dark:fill-white"
            viewBox="0 0 24 24"
            role="img"
            xmlns="http://www.w3.org/2000/svg"
        >
            <title>Framer logo</title>
            <path d="M4 0h16v8h-8zM4 8h8l8 8H4zM4 16h8v8z" />
        </svg>
    )
})
