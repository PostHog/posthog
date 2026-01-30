import React from 'react'

export const PerplexityLogo = React.memo(function PerplexityLogo(): JSX.Element {
    return (
        <svg className="h-8 w-8" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
            <title>Perplexity logo</title>
            <path
                d="M12 1L4 6.5V11H7V19H4V23H20V19H17V11H20V6.5L12 1ZM12 3.5L18 7.5V9H15V19H13V12H11V19H9V9H6V7.5L12 3.5Z"
                fill="black"
                className="dark:fill-white"
            />
        </svg>
    )
})
