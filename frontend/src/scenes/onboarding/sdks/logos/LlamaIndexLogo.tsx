import React from 'react'

export const LlamaIndexLogo = React.memo(function LlamaIndexLogo(): JSX.Element {
    return (
        <svg className="h-8 w-8" viewBox="0 0 256 256" fill="none" xmlns="http://www.w3.org/2000/svg">
            <title>LlamaIndex logo</title>
            <rect x="24" y="24" width="208" height="208" rx="32" fill="black" className="dark:fill-white" />
            <path d="M80 176V80h16v80h48v16H80zM160 176V80h16v96h-16z" fill="white" className="dark:fill-black" />
        </svg>
    )
})
