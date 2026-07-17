import React from 'react'

export const RudderstackLogo = React.memo(function RudderstackLogo(): JSX.Element {
    return (
        <svg className="h-8 w-8" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1000 1000">
            <title>RudderStack logo</title>
            <path
                d="M874.05 517.1V267.73H624.68c0 137.73 111.65 249.37 249.37 249.37ZM125.95 981.63h368.96c209.39 0 379.1-169.75 379.1-379.1H125.95v379.1Z"
                fill="#00006f"
                className="dark:fill-white"
            />
            <path
                d="M624.68 18.37c0 137.73 111.65 249.37 249.37 249.37V18.37H624.68Z"
                fill="#00006f"
                className="dark:fill-white"
            />
            <path
                d="M375.32 18.37c0 137.73 111.65 249.37 249.37 249.37H375.32c0 137.73 111.65 249.37 249.37 249.37V18.37H375.32ZM375.32 517.1V267.73H125.95c0 137.73 111.65 249.37 249.37 249.37Z"
                fill="#00006f"
                className="dark:fill-white"
            />
        </svg>
    )
})
