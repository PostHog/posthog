import React from 'react'

export const RetoolLogo = React.memo(function RetoolLogo(): JSX.Element {
    return (
        <svg className="h-8 w-8" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 42 42">
            <title>Retool logo</title>
            <g fill="black" className="dark:fill-white">
                <path d="M0,3.8C0,1.7,1.7,0,3.8,0h15.1c2.1,0,3.8,1.7,3.8,3.8v3c0,1.1-0.9,1.9-1.9,1.9H1.9C0.9,8.8,0,7.9,0,6.8V3.8z" />
                <path d="M0,15.9C0,14.9,0.9,14,1.9,14h36.2c2.1,0,3.8,1.7,3.8,3.8v10c0,1.1-0.9,1.9-1.9,1.9H3.8C1.7,29.8,0,28,0,25.9V15.9z" />
                <path d="M19.2,36.9c0-1.1,0.9-1.9,1.9-1.9h18.9c1.1,0,1.9,0.9,1.9,1.9v1.2c0,2.1-1.7,3.8-3.8,3.8H23.1c-2.1,0-3.8-1.7-3.8-3.8V36.9z" />
            </g>
        </svg>
    )
})
