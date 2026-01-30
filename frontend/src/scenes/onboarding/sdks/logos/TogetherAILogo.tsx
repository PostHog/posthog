import React from 'react'

export const TogetherAILogo = React.memo(function TogetherAILogo(): JSX.Element {
    return (
        <svg className="h-8 w-8" viewBox="0 0 24 24" fill="none" fillRule="evenodd" xmlns="http://www.w3.org/2000/svg">
            <title>Together AI logo</title>
            <path
                d="M17.385 11.23a4.615 4.615 0 100-9.23 4.615 4.615 0 000 9.23zm0 10.77a4.615 4.615 0 100-9.23 4.615 4.615 0 000 9.23zm-10.77 0a4.615 4.615 0 100-9.23 4.615 4.615 0 000 9.23z"
                opacity=".2"
                fill="black"
                className="dark:fill-white"
            />
            <circle cx="6.615" cy="6.615" fill="#0F6FFF" r="4.615" />
        </svg>
    )
})
