import React from 'react'

export const AnthropicLogo = React.memo(function AnthropicLogo(): JSX.Element {
    return (
        <svg className="h-8 w-8" viewBox="0 0 92.2 65" xmlns="http://www.w3.org/2000/svg">
            <title>Anthropic logo</title>
            <path
                d="M66.5,0H52.4l25.7,65h14.1L66.5,0z M25.7,0L0,65h14.4l5.3-13.6h26.9L51.8,65h14.4L40.5,0C40.5,0,25.7,0,25.7,0z M24.3,39.3l8.8-22.8l8.8,22.8H24.3z"
                fill="black"
                className="dark:fill-white"
            />
        </svg>
    )
})
