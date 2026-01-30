import React from 'react'

export const SemanticKernelLogo = React.memo(function SemanticKernelLogo(): JSX.Element {
    return (
        <svg className="h-8 w-8" viewBox="0 0 256 256" fill="none" xmlns="http://www.w3.org/2000/svg">
            <title>Semantic Kernel logo</title>
            <rect x="16" y="16" width="104" height="104" rx="8" fill="#F25022" />
            <rect x="136" y="16" width="104" height="104" rx="8" fill="#7FBA00" />
            <rect x="16" y="136" width="104" height="104" rx="8" fill="#00A4EF" />
            <rect x="136" y="136" width="104" height="104" rx="8" fill="#FFB900" />
        </svg>
    )
})
